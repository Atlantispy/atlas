"""I05.1 complete material records carried with the I03 cohorts (tectonics/docs/I05_MOVING_STATE.md).

A ``MovingState`` is the I05 companion of one I03 ``SphereState``: one ``CohortRecord`` per I03 cohort, holding what the
cohort's material carries by identity (layer order and the original declared profile, dates, raw plastic history
``kappa``, the irreversible bond record, compaction and elastic memory, and its declared thermal inputs), and, per
I03 piece, the signed heat of each sublayer in joules against one declared reference temperature. It is bound to the
I03 state's identity and piece order, and has its own identity over its record and arrays.

One raw history per cohort (ruling I05-2). Intensive history is keyed by cohort and follows each piece unchanged, so
I03's exact sum of same-cohort parts is always lawful for it. An update that would give pieces of one cohort different
histories refuses ``history divergence``; the caller first splits the cohort in the same interval (integration_splits,
carried in the Motion). Extensive content (sublayer heat) is divided by I03's own rows and share rule, so material and
heat share intersections, and is kept with exact rational accounts as I03 keeps its own.

``advance_moving`` is a pure transaction over one accepted I03 step: it either issues the complete successor, bound to
the step's parent state, successor state and overlap map, or refuses with the parent untouched. The I02 attachment
commits it (integration_ledger, ``moving``).

The module also holds the package reproduction of the irreversible bond record of
tools/check_i01_separation_feasibility.py (tectonics/docs/I01_SEPARATION_FEASIBILITY.md sections 1, 2 and 6). The bond
latch is material history kept separate from recoverable strength: ``ever_broken`` changes only by logical OR with an
evidenced completion of the selected cohesion-loss law, support only degrades (INSIDE, then UNKNOWN, then VIOLATED),
and nothing rewelds. The tool stays unchanged and is imported only by the parity tests.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field, replace
from fractions import Fraction
import hashlib
import json
import math

import numpy as np

from . import integration_sphere as _sphere
from . import integration_splits as _splits
from . import integration_state as _state
from . import integration_transfer as _transfer
from ._validation import TectonicsError
from .integration_ledger import LedgerError, _exact, _exact_text
from .materials import _json, _name


INVALID_INPUT = 'REFUSED_INVALID_INPUT'
SUPPORTS = ('INSIDE', 'UNKNOWN', 'VIOLATED')
BONDS = ('BONDED', 'BROKEN', 'UNRESOLVED')


class BondRefused(TectonicsError):
    """A malformed bond record or observation; ``code`` is the I01 code (REFUSED_INVALID_INPUT)."""

    def __init__(self, code, message):
        if code != INVALID_INPUT:
            raise ValueError('unknown bond refusal code')
        super().__init__(message)
        self.code = code


def _real(value, name, *, positive=False, nonnegative=False):
    if type(value) not in (int, float):
        raise BondRefused(INVALID_INPUT, name+' must be a finite real')
    try:
        value = float(value)
    except OverflowError:
        raise BondRefused(INVALID_INPUT, name+' is not representable') from None
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise BondRefused(INVALID_INPUT, name+' is outside its numeric support')
    return value


@dataclass(frozen=True)
class BondRecord:
    """One cohort's irreversible bond latch and the support of its whole history; no inferred initial certificate."""
    cohort: str
    ever_broken: bool
    support: str

    def __post_init__(self):
        if type(self.cohort) is not str or not self.cohort.strip():
            raise BondRefused(INVALID_INPUT, 'cohort identity required')
        if type(self.ever_broken) is not bool or self.support not in SUPPORTS:
            raise BondRefused(INVALID_INPUT, 'explicit bond and support histories required')

    def observe(self, law, filtered_history, temperature_k, effective_pressure_pa, *, increment_support):
        """Update the latch, never overwrite it with the current filtered strength history.

        ``law`` is the selected cohesion-loss law: it answers ``inside(T, P_eff)`` and carries ``residual_state`` and
        ``softening_history``. ``increment_support`` certifies the whole new segment and every raw-history
        contributor to this filtered value, not just the endpoint temperature and pressure.
        """
        history = _real(filtered_history, 'filtered history', nonnegative=True)
        temperature = _real(temperature_k, 'temperature', positive=True)
        pressure = _real(effective_pressure_pa, 'effective pressure', nonnegative=True)
        if increment_support not in SUPPORTS:
            raise BondRefused(INVALID_INPUT, 'whole-segment support must be explicit')
        records = (self.support, increment_support)
        support = ('VIOLATED' if 'VIOLATED' in records or not law.inside(temperature, pressure)
                   else 'UNKNOWN' if 'UNKNOWN' in records else 'INSIDE')
        broke = (self.ever_broken or (support == 'INSIDE'
                 and law.residual_state == 'broken_surface_sliding'
                 and history >= law.softening_history))
        return replace(self, ever_broken=broke, support=support)

    @property
    def bond(self):
        """BROKEN once evidenced, whatever later support; BONDED only with INSIDE support; otherwise UNRESOLVED."""
        return 'BROKEN' if self.ever_broken else 'BONDED' if self.support == 'INSIDE' else 'UNRESOLVED'


def preserve_bond_records(records):
    """Distinct identities, never averaged flags: refuse an empty set, a foreign item or a duplicate cohort."""
    records = tuple(records)
    if not records or any(not isinstance(record, BondRecord) for record in records):
        raise BondRefused(INVALID_INPUT, 'explicit material bond records required')
    if len({record.cohort for record in records}) != len(records):
        raise BondRefused(INVALID_INPUT, 'duplicate cohort identity; a spatial remapper must retain support')
    return records


# ----------------------------------------------------------------------------- the transported record schema

LEGACY_SCHEMA = 'atlas.i05-moving-state.v1'
PATCH_SCHEMA = 'atlas.i05-moving-state.v2'
SCHEMA = 'atlas.i05-moving-state.v3'
RADIAL_SCHEMA = 'atlas.i05-moving-state.v4'
ADVANCE_SCHEMA = 'atlas.i05-moving-advance.v1'
HEATED_ADVANCE_SCHEMA = 'atlas.i05-moving-advance.v2'
PATCH_ADVANCE_SCHEMA = 'atlas.i05-moving-advance.v3'
RADIAL_ADVANCE_SCHEMA = 'atlas.i05-moving-advance.v4'
PRODUCER = 'atlas_tectonics.integration_material'
NOT_REPRESENTED = 'NOT_REPRESENTED'
MAX_SUBLAYERS = 32                       # the I01_GPE / P1 column representation bound
CONDUCTION_PARTY = 'i05|conduction'
MECHANICAL_HEAT_PARTY = 'i05|mechanical-dissipation'
UNKNOWN_BOUND = 'UNKNOWN'                # the carried lateral-omission bound after an interval without conduction

STALE = 'stale identity'
MISSING = 'missing record'
INCOMPATIBLE = 'incompatible support'
DIVERGENCE = 'history divergence'
UNRESOLVED = 'unresolved overlap'
UNSUPPORTED = 'unsupported'
CODES = (STALE, MISSING, INCOMPATIBLE, DIVERGENCE, UNRESOLVED, UNSUPPORTED)


class TransportRefused(TectonicsError):
    """An I05 record, transport or update that is refused whole; ``code`` is one of CODES and ``detail`` names what."""

    def __init__(self, message, code, detail=None):
        if code not in CODES:
            raise ValueError('unknown I05 transport refusal code')
        super().__init__('%s (%s)' % (message, code))
        self.code = code
        self.detail = detail


def _number(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.floating, np.integer)):
        raise TransportRefused(label+' must be a finite real', MISSING, label)
    try:
        value = float(value)
    except (TypeError, OverflowError):
        raise TransportRefused(label+' must be a finite real', MISSING, label) from None
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise TransportRefused(label+' is outside its finite support', MISSING, label)
    return value


def _text(value, label):
    try:
        return _name(value, label)
    except TectonicsError as exc:
        raise TransportRefused(str(exc), MISSING, label) from exc


def _optional(value, label, **kwargs):
    return None if value is None else _number(value, label, **kwargs)


@dataclass(frozen=True)
class Sublayer:
    """One declared sublayer of a cohort's column, top down: material, I03 phase and the declared IN-05 inputs.

    ``thickness_m`` and the boundary temperatures are the declared original profile, never reset by motion or heating;
    the current thickness follows the I03 phase volume. Heat capacity is one constant per material (ruling I05-4): heat
    content goes through the caloric form H(T) = cp (T - T_ref) and its inverse, where a later admitted cp(T) law would
    slot in. ``creep_law_id`` and ``pore_pressure_pa`` are declared strength inputs for P2; None is unknown.
    """
    material_id: str
    phase: str
    thickness_m: float
    reference_density_kg_m3: float
    alpha_per_k: float
    conductivity_w_m_k: float
    heat_capacity_j_kg_k: float
    radiogenic_w_m3: float
    top_temperature_k: float
    bottom_temperature_k: float
    creep_law_id: object = None
    pore_pressure_pa: object = None

    def __post_init__(self):
        for name in ('material_id', 'phase'):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ('thickness_m', 'reference_density_kg_m3', 'conductivity_w_m_k', 'heat_capacity_j_kg_k',
                     'top_temperature_k', 'bottom_temperature_k'):
            object.__setattr__(self, name, _number(getattr(self, name), name, positive=True))
        for name in ('alpha_per_k', 'radiogenic_w_m3'):
            object.__setattr__(self, name, _number(getattr(self, name), name, nonnegative=True))
        if self.creep_law_id is not None:
            object.__setattr__(self, 'creep_law_id', _text(self.creep_law_id, 'creep_law_id'))
        object.__setattr__(self, 'pore_pressure_pa', _optional(self.pore_pressure_pa, 'pore_pressure_pa',
                                                               nonnegative=True))

    def caloric(self, temperature_k, reference_k):
        """Specific heat content H(T) = integral of cp from T_ref to T, in J/kg (constant cp: cp (T - T_ref))."""
        return self.heat_capacity_j_kg_k*(temperature_k-reference_k)

    def temperature(self, specific_heat_j_kg, reference_k):
        """The inverse of the caloric form: the temperature whose H is ``specific_heat_j_kg``."""
        return reference_k+specific_heat_j_kg/self.heat_capacity_j_kg_k

    def declared_heat_per_area(self, reference_k):
        """Heat of the declared sublayer per unit area, J/m2: rho h times the mean of H over its linear profile.

        Exact for the admitted linear caloric law, for which the mean of H is H of the mean temperature.
        """
        mean = (self.caloric(self.top_temperature_k, reference_k)+self.caloric(self.bottom_temperature_k,
                                                                                reference_k))/2
        return self.reference_density_kg_m3*self.thickness_m*mean

    def record(self):
        return dict(material_id=self.material_id, phase=self.phase, thickness_m=self.thickness_m,
                    reference_density_kg_m3=self.reference_density_kg_m3, alpha_per_k=self.alpha_per_k,
                    conductivity_w_m_k=self.conductivity_w_m_k, heat_capacity_j_kg_k=self.heat_capacity_j_kg_k,
                    radiogenic_w_m3=self.radiogenic_w_m3, top_temperature_k=self.top_temperature_k,
                    bottom_temperature_k=self.bottom_temperature_k, creep_law_id=self.creep_law_id,
                    pore_pressure_pa=self.pore_pressure_pa)


@dataclass(frozen=True)
class CompactionMemory:
    """Carried drained-compaction memory of a cohort's parcels (R-8): void ratio and peak effective stress per parcel.

    It moves with its cohort by identity and is never reset; the drained law itself is not applied on moving I03
    columns (ruling I05-8).
    """
    law_id: str
    conditions_id: str
    parcels: tuple                       # ((parcel_id, void_ratio, peak_effective_stress_pa), ...), top down

    def __post_init__(self):
        object.__setattr__(self, 'law_id', _text(self.law_id, 'compaction law'))
        object.__setattr__(self, 'conditions_id', _text(self.conditions_id, 'drained conditions'))
        if type(self.parcels) not in (tuple, list) or not self.parcels:
            raise TransportRefused('compaction memory names its parcels', MISSING, 'parcels')
        rows = tuple((_text(p, 'parcel'), _number(e, 'void ratio', nonnegative=True),
                      _number(s, 'peak effective stress', nonnegative=True)) for p, e, s in self.parcels)
        if len({row[0] for row in rows}) != len(rows):
            raise TransportRefused('each parcel once', INCOMPATIBLE, 'parcels')
        object.__setattr__(self, 'parcels', rows)

    def record(self):
        return dict(law_id=self.law_id, conditions_id=self.conditions_id, parcels=[list(row) for row in self.parcels])


@dataclass(frozen=True)
class ElasticMemory:
    """Carried coaxial stress/stretch memory (R-7), the I01 elastic-memory State fields plus frame and plane.

    Carried by identity only: never interpolated, averaged or reset, never written as zero. Every current route
    carries NOT_REPRESENTED instead (I02 persists no elastic branch).
    """
    stress_pa: float
    axis_rad: float
    log_stretch: float
    shear_modulus_pa: float
    time_s: float
    frame_id: str
    plane: str
    modulus_source: str
    support: str

    def __post_init__(self):
        for name in ('stress_pa', 'axis_rad', 'log_stretch', 'time_s'):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        object.__setattr__(self, 'shear_modulus_pa', _number(self.shear_modulus_pa, 'shear modulus', positive=True))
        if abs(self.log_stretch) > 1. or abs(self.stress_pa)/(2*self.shear_modulus_pa) > .01 or self.time_s < 0:
            raise TransportRefused('elastic memory outside the I01 control bounds (|log stretch| <= 1, elastic '
                                   'strain <= 0.01): it is handed to I07, never clipped or rebased', UNSUPPORTED,
                                   'elastic memory')
        for name in ('frame_id', 'plane', 'modulus_source'):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.support not in SUPPORTS:
            raise TransportRefused('elastic memory support must be explicit', MISSING, 'support')

    def record(self):
        return {name: getattr(self, name) for name in ('stress_pa', 'axis_rad', 'log_stretch', 'shear_modulus_pa',
                                                       'time_s', 'frame_id', 'plane', 'modulus_source', 'support')}


def _memory(value, kind, label):
    if value == NOT_REPRESENTED:
        return NOT_REPRESENTED
    if type(value) is not kind:
        raise TransportRefused('%s is NOT_REPRESENTED or a %s, never zero or absent' % (label, kind.__name__),
                               MISSING, label)
    return value


@dataclass(frozen=True)
class CohortRecord:
    """What one cohort's material carries by identity; one raw history per cohort (ruling I05-2).

    ``sublayers`` are top down. ``kappa`` holds the raw plastic history at each sublayer's material point: it never
    decreases and is never filtered. The formation interval is the I03 cohort's own; ``cooling_start_s`` dates the
    declared thermal history (None is unknown, never zero). The surface and base conditions are the declared IN-05
    boundary inputs of the column's conduction (base None is insulated).
    """
    cohort_id: str
    profile_id: str
    thermal_source: str
    sublayers: tuple
    surface_temperature_k: float
    base_temperature_k: object
    cooling_start_s: object
    kappa: tuple
    bond: BondRecord
    compaction: object = NOT_REPRESENTED
    elastic: object = NOT_REPRESENTED
    volume_convention: str = 'reference_prism'
    reference_radius_m: object = None
    radial_depths_m: object = None

    def __post_init__(self):
        for name in ('cohort_id', 'profile_id', 'thermal_source'):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if (type(self.sublayers) not in (tuple, list) or not 1 <= len(self.sublayers) <= MAX_SUBLAYERS
                or any(type(s) is not Sublayer for s in self.sublayers)):
            raise TransportRefused('a cohort record declares 1 to %d Sublayer records' % MAX_SUBLAYERS, MISSING,
                                   'sublayers')
        object.__setattr__(self, 'sublayers', tuple(self.sublayers))
        phases = [s.phase for s in self.sublayers]
        if any(phases.index(p) != i and phases[i-1] != p for i, p in enumerate(phases)):
            raise TransportRefused('the sublayers of one phase are contiguous', INCOMPATIBLE, 'sublayers')
        object.__setattr__(self, 'surface_temperature_k', _number(self.surface_temperature_k, 'surface temperature',
                                                                  positive=True))
        object.__setattr__(self, 'base_temperature_k', _optional(self.base_temperature_k, 'base temperature',
                                                                 positive=True))
        object.__setattr__(self, 'cooling_start_s', _optional(self.cooling_start_s, 'cooling start'))
        if type(self.kappa) not in (tuple, list) or len(self.kappa) != len(self.sublayers):
            raise TransportRefused('raw plastic history at every sublayer material point', MISSING, 'kappa')
        object.__setattr__(self, 'kappa', tuple(_number(k, 'kappa', nonnegative=True) for k in self.kappa))
        if type(self.bond) is not BondRecord or self.bond.cohort != self.cohort_id:
            raise TransportRefused("a cohort record carries its own cohort's BondRecord", MISSING, 'bond')
        object.__setattr__(self, 'compaction', _memory(self.compaction, CompactionMemory, 'compaction memory'))
        object.__setattr__(self, 'elastic', _memory(self.elastic, ElasticMemory, 'elastic memory'))
        from .integration_volume import REFERENCE_PRISM, PHYSICAL_RADIAL_SHELL
        if type(self.volume_convention) is not str or self.volume_convention not in (REFERENCE_PRISM, PHYSICAL_RADIAL_SHELL):
            raise TransportRefused('an explicit supported volume convention is required', UNSUPPORTED,
                                   'volume_convention')
        if self.volume_convention == REFERENCE_PRISM:
            if self.reference_radius_m is not None or self.radial_depths_m is not None:
                raise TransportRefused('reference prism does not declare a shell radius', INCOMPATIBLE,
                                       'reference_radius_m')
        else:
            radius = _number(self.reference_radius_m, 'reference_radius_m', positive=True)
            if sum((Fraction(s.thickness_m) for s in self.sublayers), Fraction(0)) >= Fraction(radius):
                raise TransportRefused('radial columns must stop strictly above the centre', UNSUPPORTED,
                                       'reference_radius_m')
            object.__setattr__(self, 'reference_radius_m', radius)
            if self.radial_depths_m is not None:
                depths = tuple(_number(z, 'radial depth', nonnegative=True) for z in self.radial_depths_m)
                if (len(depths) != len(self.sublayers)+1 or depths[0] != 0. or depths[-1] >= radius or
                        any(not a < b or s.thickness_m != float(Fraction(b)-Fraction(a))
                            for a, b, s in zip(depths, depths[1:], self.sublayers))):
                    raise TransportRefused('radial interfaces must match their declared height differences',
                                           INCOMPATIBLE, 'radial_depths_m')
                object.__setattr__(self, 'radial_depths_m', depths)

    def phase_thickness(self, phase):
        return math.fsum(s.thickness_m for s in self.sublayers if s.phase == phase)

    def renamed(self, cohort_id):
        """The same carried content under a sub-cohort's identity (a history split copies, never averages)."""
        return replace(self, cohort_id=cohort_id, bond=replace(self.bond, cohort=cohort_id))

    def record(self):
        row = dict(cohort_id=self.cohort_id, profile_id=self.profile_id, thermal_source=self.thermal_source,
                    sublayers=[s.record() for s in self.sublayers],
                    surface_temperature_k=self.surface_temperature_k, base_temperature_k=self.base_temperature_k,
                    cooling_start_s=self.cooling_start_s, kappa=list(self.kappa),
                    bond=dict(ever_broken=self.bond.ever_broken, support=self.bond.support),
                    compaction=self.compaction if self.compaction == NOT_REPRESENTED else self.compaction.record(),
                    elastic=self.elastic if self.elastic == NOT_REPRESENTED else self.elastic.record())
        if self.volume_convention != 'reference_prism':
            row.update(volume_convention=self.volume_convention, reference_radius_m=self.reference_radius_m)
            if self.radial_depths_m is not None:
                row['radial_depths_m'] = list(self.radial_depths_m)
        return row

    @staticmethod
    def from_record(row):
        def memory(value, kind):
            return NOT_REPRESENTED if value == NOT_REPRESENTED else kind(**value)
        try:
            compaction = row['compaction']
            if compaction != NOT_REPRESENTED:
                compaction = CompactionMemory(compaction['law_id'], compaction['conditions_id'],
                                              tuple(tuple(p) for p in compaction['parcels']))
            return CohortRecord(row['cohort_id'], row['profile_id'], row['thermal_source'],
                                tuple(Sublayer(**s) for s in row['sublayers']), row['surface_temperature_k'],
                                row['base_temperature_k'], row['cooling_start_s'], tuple(row['kappa']),
                                BondRecord(row['cohort_id'], row['bond']['ever_broken'], row['bond']['support']),
                                compaction, memory(row['elastic'], ElasticMemory),
                                row.get('volume_convention', 'reference_prism'), row.get('reference_radius_m'),
                                row.get('radial_depths_m'))
        except (KeyError, TypeError, ValueError, BondRefused) as exc:
            raise TransportRefused('a stored cohort record is incomplete', MISSING, 'cohort record') from exc


def birth_record(cohort_id, column):
    """The record of a cohort born from a supply: its column with zero raw history and the declared bond support."""
    if type(column) is not BirthColumn:
        raise TransportRefused('a birth column is required', MISSING, 'birth column')
    return CohortRecord(cohort_id, column.profile_id, column.thermal_source, column.sublayers,
                        column.surface_temperature_k, column.base_temperature_k, None,
                        (0.,)*len(column.sublayers), BondRecord(cohort_id, False, column.bond_support),
                        volume_convention=column.volume_convention, reference_radius_m=column.reference_radius_m,
                        radial_depths_m=column.radial_depths_m)


@dataclass(frozen=True)
class BirthColumn:
    """The I05 content behind a ridge supply's history reference: the born column with its declared temperatures.

    Its sublayers must reproduce the supply's thickness and reference mass per phase, and its declared temperatures
    give the born heat per area. Raw history starts at zero; the bond support is declared, never inferred.
    """
    profile_id: str
    thermal_source: str
    sublayers: tuple
    surface_temperature_k: float
    base_temperature_k: object
    bond_support: str = 'UNKNOWN'
    volume_convention: str = 'reference_prism'
    reference_radius_m: object = None
    radial_depths_m: object = None

    def __post_init__(self):
        record = CohortRecord('birth', self.profile_id, self.thermal_source, self.sublayers,
                              self.surface_temperature_k, self.base_temperature_k, None, (0.,)*len(self.sublayers)
                              if type(self.sublayers) in (tuple, list) else (), BondRecord('birth', False, 'UNKNOWN'),
                              volume_convention=self.volume_convention, reference_radius_m=self.reference_radius_m,
                              radial_depths_m=self.radial_depths_m)
        object.__setattr__(self, 'sublayers', record.sublayers)
        object.__setattr__(self, 'surface_temperature_k', record.surface_temperature_k)
        object.__setattr__(self, 'base_temperature_k', record.base_temperature_k)
        object.__setattr__(self, 'reference_radius_m', record.reference_radius_m)
        object.__setattr__(self, 'radial_depths_m', record.radial_depths_m)
        if self.bond_support not in SUPPORTS:
            raise TransportRefused('a born cohort declares its bond support', MISSING, 'bond_support')

    def record(self):
        row = dict(profile_id=self.profile_id, thermal_source=self.thermal_source,
                    sublayers=[s.record() for s in self.sublayers], surface_temperature_k=self.surface_temperature_k,
                    base_temperature_k=self.base_temperature_k, bond_support=self.bond_support)
        if self.volume_convention != 'reference_prism':
            row.update(volume_convention=self.volume_convention, reference_radius_m=self.reference_radius_m)
            if self.radial_depths_m is not None:
                row['radial_depths_m'] = list(self.radial_depths_m)
        return row

    @staticmethod
    def from_record(row):
        try:
            return BirthColumn(row['profile_id'], row['thermal_source'], tuple(Sublayer(**s) for s in row['sublayers']),
                               row['surface_temperature_k'], row['base_temperature_k'], row['bond_support'],
                               row.get('volume_convention', 'reference_prism'), row.get('reference_radius_m'),
                               row.get('radial_depths_m'))
        except (KeyError, TypeError, ValueError) as exc:
            raise TransportRefused('a stored birth column is incomplete', MISSING, 'birth column') from exc


# ----------------------------------------------------------------------------- the state

def layer_geometry(record, heights=None, *, budget=None):
    """Exact radial layer geometry; no inference of a shell from a prism record."""
    from .integration_volume import RadialLayer, PHYSICAL_RADIAL_SHELL
    if record.volume_convention != PHYSICAL_RADIAL_SHELL:
        raise TransportRefused('radial layer geometry requires a physical shell declaration', UNSUPPORTED,
                               'volume_convention')
    heights = tuple(s.thickness_m for s in record.sublayers) if heights is None else tuple(heights)
    if len(heights) != len(record.sublayers):
        raise TransportRefused('one radial height per sublayer is required', MISSING, 'heights')
    if tuple(heights) != tuple(s.thickness_m for s in record.sublayers):
        raise TransportRefused('radial deformation needs an actual changed interface map', UNSUPPORTED, 'heights')
    if record.radial_depths_m is not None:
        return tuple(RadialLayer(record.reference_radius_m, a, b, budget=budget)
                     for a, b in zip(record.radial_depths_m, record.radial_depths_m[1:]))
    out, depth = [], Fraction(0)
    for h in heights:
        bottom = depth+Fraction(h)
        if bottom >= Fraction(record.reference_radius_m):
            raise TransportRefused('radial columns must stop strictly above the centre', UNSUPPORTED, 'heights')
        out.append(RadialLayer(record.reference_radius_m, depth, bottom, budget=budget))
        depth = bottom
    return tuple(out)


def volume_per_area(record, heights=None, *, budget=None):
    heights = tuple(s.thickness_m for s in record.sublayers) if heights is None else tuple(heights)
    return (tuple(Fraction(h) for h in heights) if record.volume_convention == 'reference_prism' else
            tuple(g.volume_per_area_m for g in layer_geometry(record, heights, budget=budget)))


def phase_volume_per_area(record, heights=None, *, budget=None):
    out = {}
    for s, weight in zip(record.sublayers, volume_per_area(record, heights, budget=budget)):
        out[s.phase] = out.get(s.phase, Fraction(0))+weight
    return out


def declared_areal_heat(record, reference, *, budget=None):
    """Exact declared heat law per outer area; preserve historical prism arithmetic."""
    if record.volume_convention == 'reference_prism':
        return tuple(Fraction(s.declared_heat_per_area(reference)) for s in record.sublayers)
    return tuple(Fraction(s.reference_density_kg_m3)*Fraction(s.heat_capacity_j_kg_k)*(
        g.integrate_linear_per_area(s.top_temperature_k, s.bottom_temperature_k)
        -Fraction(reference)*g.volume_per_area_m) for s, g in zip(record.sublayers, layer_geometry(record, budget=budget)))


def _thickness_ratios(record, piece, phases, *, budget=None):
    """Current over declared thickness of each sublayer of ``piece``: the phase volume over area, shared by the
    sublayers of one phase (uniform strain within a phase, declared). Exact transport keeps the declared ratio."""
    if record.volume_convention != 'reference_prism':
        expected = phase_volume_per_area(record, budget=budget)
        for phase, volume in zip(phases, piece.volume_m3):
            target = expected.get(phase, Fraction(0))*Fraction(piece.area_m2)
            if abs(target-Fraction(volume)) > Fraction(_sphere.RELATIVE_TOLERANCE)*max(abs(target), abs(Fraction(volume))):
                raise TransportRefused('shell volume is incompatible with its retained radial heights',
                                       INCOMPATIBLE, 'radial volume')
        return [1.]*len(record.sublayers)
    out = []
    volume = dict(zip(phases, piece.volume_m3))
    for sublayer in record.sublayers:
        out.append(volume[sublayer.phase]/piece.area_m2/record.phase_thickness(sublayer.phase))
    return out


@dataclass(frozen=True, init=False, eq=False, slots=True)
class MovingState(_state._Immutable):
    """The I05 state of one I03 state: cohort records and per-piece sublayer heat with exact accounts.

    Pieces are the I03 material's, in its order; ``heat_j(i)`` holds piece i's sublayers top down. The exact accounts
    obey sum(stored heat) = initial + sum(supplied) + rounding, |rounding| <= allowance, as I03's accounts do. The
    record also carries the MC-06 temperature-error bound of every lateral omission so far
    (``lateral_omission_error_k``, zero when declared; the least binary64 value not below the exact bound, so it stays
    an upper bound with a bounded record): a continuation starts from it, never from zero.
    """
    state_id: str
    network_id: str
    material_id: str
    time_s: float
    step: int
    declared_step: int
    frame_id: str
    enthalpy_reference_k: float
    cohorts: tuple
    moving_id: str
    _pieces: tuple = field(repr=False)
    _offsets: np.ndarray = field(repr=False)
    _heat: np.ndarray = field(repr=False)
    _initial: Fraction = field(repr=False)
    _supplied: tuple = field(repr=False)
    _rounding: Fraction = field(repr=False)
    _allowance: Fraction = field(repr=False)
    _lateral_error: Fraction = field(repr=False)
    _record: bytes = field(repr=False)
    _packed: tuple = field(repr=False)
    _patch_heat: object = field(repr=False)
    _projection_rounding: Fraction = field(repr=False)
    _physical_columns: object = field(repr=False)
    _physical_account: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('MovingState is issued by declare_moving(), advance_moving() or restore_moving() only')

    def cohort(self, cohort_id):
        for record in self.cohorts:
            if record.cohort_id == cohort_id:
                return record
        raise TransportRefused('unknown cohort %r' % (cohort_id,), MISSING, cohort_id)

    @property
    def pieces(self):
        """(face_id, cohort_id) of every piece, in the I03 material's order."""
        return self._pieces

    def heat_j(self, index):
        """Reporting projection; use patch_heat_exact for the positioned thermal state."""
        return self._heat[self._offsets[index]:self._offsets[index+1]].copy()

    def patch_heat_exact(self, patch_id):
        if self._patch_heat is None:
            raise TransportRefused('this historical moving state has no positioned heat; no implicit '
                                   'reconstruction from a piece mean', UNSUPPORTED, 'patch_heat')
        try:
            return dict(self._patch_heat)[patch_id]
        except KeyError:
            raise TransportRefused('no heat for the requested material patch', MISSING, 'patch_heat') from None

    def supplied(self):
        return {name: value for name, value in self._supplied}

    def closure(self):
        total = (sum((Fraction(float(x)) for x in self._heat), Fraction(0)) if self._patch_heat is None else
                 sum((v for _, column in self._patch_heat for v in column), Fraction(0)))
        booked = self._initial+sum((value for _, value in self._supplied), Fraction(0))+self._rounding
        out = dict(identity_exact=total == booked and abs(self._rounding) <= self._allowance,
                    stored_j=float(total), rounding_j=float(self._rounding), allowance_j=float(self._allowance),
                    piece_projection_rounding_j=float(self._projection_rounding))
        if self._physical_account is not None:
            out['physical_column_account'] = json.loads(self._physical_account)
        return out

    def descriptor(self):
        return dict(json.loads(self._record), moving_id=self.moving_id)

    def arrays(self):
        return {'moving.'+name: array.view() for name, array in self._packed}


def _accounts_record(initial, supplied, rounding, allowance):
    try:
        return dict(initial=_exact_text(initial), supplied={name: _exact_text(value) for name, value in supplied},
                    rounding=_exact_text(rounding), allowance=_exact_text(allowance))
    except LedgerError as exc:
        raise TransportRefused('an exact heat account leaves its bounded representation', UNSUPPORTED,
                               'accounts') from exc


def _issued(sphere, cohorts, heat, initial, supplied, rounding, allowance, reference, lateral_error=Fraction(0),
            declared_step=None, *, patch_heat=None, legacy=False, physical_columns=None, budget=None):
    """Check the join with the I03 state and the exact accounts, then issue the state with its identity.
    ``declared_step`` is the network step of the declaration this state descends from (default: this state's)."""
    if type(sphere) is not _sphere.SphereState:
        raise TransportRefused('a moving state is issued only beside its I03 SphereState', STALE, 'state')
    declared_step = sphere.network.step if declared_step is None else declared_step
    if type(declared_step) is not int or not 0 <= declared_step <= sphere.network.step:
        raise TransportRefused('the declaration step is a whole step no later than the state\'s', MISSING,
                               'declared_step')
    if lateral_error is not None and (type(lateral_error) is not Fraction or lateral_error < 0):
        raise TransportRefused('the carried lateral-omission bound is an exact nonnegative number or UNKNOWN', MISSING,
                               'lateral_omission_error_k')
    material = sphere.material
    if material.enthalpy_basis is not None:
        raise TransportRefused('I05 owns the heat of an attached moving state: the I03 material must carry no '
                               'enthalpy basis of its own (one owner per quantity)', INCOMPATIBLE, 'enthalpy_basis')
    records = tuple(sorted(cohorts, key=lambda r: r.cohort_id))
    if [r.cohort_id for r in records] != sorted(c.cohort_id for c in material.cohorts):
        raise TransportRefused('one cohort record for every cohort of the I03 material', MISSING, 'cohorts')
    by_id = {r.cohort_id: r for r in records}
    radial = any(r.volume_convention != 'reference_prism' for r in records)
    if radial:
        if legacy or physical_columns is None:
            raise TransportRefused('physical shell records require retained physical columns', UNSUPPORTED,
                                   'physical_columns')
        for r in records:
            if r.volume_convention != 'reference_prism' and r.reference_radius_m != sphere.network.sphere.radius_m:
                raise TransportRefused('shell radius is not the actual source sphere radius', STALE,
                                       'reference_radius_m')
    pieces = tuple((p.face_id, p.cohort_id) for p in material.pieces())
    patch_rows, projection = None, Fraction(0)
    if not legacy:
        from . import integration_patch_heat as _patch_heat
        if patch_heat is None:
            if sphere.issued_by != _state.DECLARED:
                raise TransportRefused('computed heat requires explicit positioned patch values', UNSUPPORTED,
                                       'patch_heat')
            patch_heat = _patch_heat.seed(sphere, pieces, heat)
        patch_rows = _patch_heat.checked(sphere, by_id, patch_heat)
        projected, projection = _patch_heat.project(sphere, patch_heat)
        if projected != [list(column) for column in heat]:
            raise TransportRefused('piece heat is not its patch reporting projection', UNRESOLVED, 'heat')
    if len(heat) != len(pieces):
        raise TransportRefused('one heat column for every I03 piece', MISSING, 'heat')
    offsets, values = [0], []
    for (face, cohort), column in zip(pieces, heat):
        if len(column) != len(by_id[cohort].sublayers):
            raise TransportRefused('piece (%r, %r) needs one heat value per sublayer' % (face, cohort), MISSING,
                                   'heat')
        values.extend(column)
        offsets.append(len(values))
    heat_array = _sphere._frozen(np.asarray(values, dtype=np.float64), np.float64)
    if not np.isfinite(heat_array).all():
        raise TransportRefused('heat must be finite', MISSING, 'heat')
    supplied = tuple(sorted(supplied))
    total = (sum((Fraction(float(x)) for x in heat_array), Fraction(0)) if patch_rows is None else
             sum((v for _, column in patch_rows for v in column), Fraction(0)))
    if total != initial+sum((v for _, v in supplied), Fraction(0))+rounding or abs(rounding) > allowance:
        raise TransportRefused('the exact heat accounts do not close on the stored pieces: nothing is issued',
                               UNRESOLVED, 'accounts')
    packed = (('cohorts', _sphere._pack([r.record() for r in records])),
              ('heat_offsets', _sphere._frozen(np.asarray(offsets, dtype=np.int64), np.int64)),
              ('heat_j', heat_array))
    if patch_rows is not None:
        packed += (('patch_heat', _sphere._pack(_patch_heat.record(dict(patch_rows)))),)
    physical_rows, physical_account = None, None
    if physical_columns is not None:
        if legacy or patch_rows is None:
            raise TransportRefused('physical columns require positioned heat', UNSUPPORTED, 'physical_columns')
        from .resources import select_budget
        with select_budget(budget).reserve(_patch_heat.field_workspace(physical_columns),
                                          category='i05-physical-column-record'):
            physical_account = _patch_heat.checked_fields(sphere, by_id, dict(patch_rows), physical_columns,
                                                          reference, sphere.network.step-declared_step, budget=budget)
            physical_rows = tuple(sorted(physical_columns.items()))
            packed += (('physical_columns', _sphere._pack(_patch_heat.field_record(physical_columns))),)
    network = sphere.network
    described = dict(
        schema=LEGACY_SCHEMA if legacy else (RADIAL_SCHEMA if radial else
                                            SCHEMA if physical_rows is not None else PATCH_SCHEMA),
        producer=PRODUCER, state_id=sphere.state_id, network_id=network.network_id,
        material_id=material.material_id, time_s=network.time_s, step=network.step, declared_step=declared_step,
        frame_id=network.sphere.frame_id,
        enthalpy_reference_k=reference, quantities=dict(heat_j='J, signed, per piece and sublayer, against '
                                                               'enthalpy_reference_k'),
        accounts=_accounts_record(initial, supplied, rounding, allowance),
        lateral_omission_error_k=(UNKNOWN_BOUND if lateral_error is None else
                                  _accounts_record(lateral_error, (), Fraction(0), Fraction(0))['initial']),
        counts=dict(cohorts=len(records), pieces=len(pieces), values=len(values)),
        arrays=[dict(name=name, dtype=array.dtype.str, shape=list(array.shape)) for name, array in packed])
    if not legacy:
        described['patch_heat'] = dict(authoritative='exact dyadic heat on retained material patches',
                                       piece_projection_rounding_j=_exact_text(projection))
    if physical_rows is not None:
        described['physical_columns'] = dict(representation='retained physical h and exact areal sensible heat',
            historical_reconstruction=False, account=physical_account, patches=len(physical_rows),
            rational_codec=_patch_heat.RATIONAL_CODEC)
    record = _sphere._canonical(described, 'moving state record')
    return _state._issue(MovingState, state_id=sphere.state_id, network_id=network.network_id,
                         material_id=material.material_id, time_s=network.time_s, step=network.step,
                         declared_step=declared_step,
                         frame_id=network.sphere.frame_id, enthalpy_reference_k=reference, cohorts=records,
                         moving_id=_sphere._identity(record, packed), _pieces=pieces,
                         _offsets=packed[1][1], _heat=heat_array, _initial=initial, _supplied=supplied,
                         _rounding=rounding, _allowance=allowance, _lateral_error=lateral_error, _record=record,
                         _packed=packed, _patch_heat=patch_rows, _projection_rounding=projection,
                         _physical_columns=physical_rows,
                         _physical_account=None if physical_account is None else _json(physical_account))


def _check_columns(sphere, records):
    """Each piece's declared phases are the cohort record's, with the declared thickness (I03 tolerance)."""
    by_id = {r.cohort_id: r for r in records}
    for r in records:
        if r.volume_convention != 'reference_prism' and r.reference_radius_m != sphere.network.sphere.radius_m:
            raise TransportRefused('shell radius is not the actual source sphere radius', STALE,
                                   'reference_radius_m')
    phases = set(sphere.material.phases)
    for piece in sphere.material.pieces():
        record = by_id.get(piece.cohort_id)
        if record is None:
            raise TransportRefused('cohort %r has no record' % piece.cohort_id, MISSING, piece.cohort_id)
        declared = {s.phase for s in record.sublayers}
        if not declared <= phases:
            raise TransportRefused('cohort %r declares a phase the I03 material does not carry' % piece.cohort_id,
                                   INCOMPATIBLE, piece.cohort_id)
        for phase, volume in zip(sphere.material.phases, piece.volume_m3):
            if phase not in declared and volume != 0:
                raise TransportRefused('piece (%r, %r) holds %r, which its record does not represent'
                                       % (piece.face_id, piece.cohort_id, phase), INCOMPATIBLE, piece.cohort_id)


def declare_moving(sphere, records, *, enthalpy_reference_k, budget=None):
    """Declare actual positioned physical profiles and their separate rounded heat accounts."""
    if (type(sphere) is not _sphere.SphereState or type(records) not in (tuple, list) or
            any(type(r) is not CohortRecord for r in records)):
        raise TransportRefused('a sphere and CohortRecord records are required', MISSING, 'declaration')
    from .resources import select_budget
    sizes = {r.cohort_id: len(r.sublayers) for r in records}
    count = sum(sizes.get(p.cohort_id, MAX_SUBLAYERS) for p in sphere.material.support.patches)
    with select_budget(budget).reserve(65536+16384*count, category='i05-physical-column-declare'):
        return _declare_moving(sphere, records, enthalpy_reference_k=enthalpy_reference_k, budget=budget)


def _declare_moving(sphere, records, *, enthalpy_reference_k, budget):
    """The declared I05 state of a declared I03 state: each piece's heat from its cohort's declared profile.

    ``records`` holds one CohortRecord per I03 cohort; ``enthalpy_reference_k`` is the required declared IN-05
    reference temperature of every heat value. Each piece must hold its cohort's declared thickness per phase within
    I03's relative tolerance; heat is the declared heat per area of each sublayer times the piece's area and its
    thickness ratio. Nothing is assumed: a missing record, phase or reference refuses.
    """
    if type(sphere) is not _sphere.SphereState or sphere.issued_by != _state.DECLARED:
        raise TransportRefused('a declared I03 SphereState is required', STALE, 'state')
    reference = _number(enthalpy_reference_k, 'enthalpy_reference_k', positive=True)
    if type(records) not in (tuple, list) or any(type(r) is not CohortRecord for r in records):
        raise TransportRefused('CohortRecord records are required', MISSING, 'cohorts')
    if len({r.cohort_id for r in records}) != len(records):
        raise TransportRefused('one record per cohort', INCOMPATIBLE, 'cohorts')
    _check_columns(sphere, records)
    by_id = {r.cohort_id: r for r in records}
    heat = []
    for piece in sphere.material.pieces():
        record = by_id[piece.cohort_id]
        ratios = _thickness_ratios(record, piece, sphere.material.phases, budget=budget)
        for ratio, sublayer in zip(ratios, record.sublayers):
            if abs(ratio-1) > _sphere.RELATIVE_TOLERANCE:
                raise TransportRefused('piece (%r, %r) does not hold its declared %r thickness'
                                       % (piece.face_id, piece.cohort_id, sublayer.phase), INCOMPATIBLE,
                                       piece.cohort_id)
        _check_reference_mass(record, piece, ratios, sphere.material.phases, 0, budget=budget)
        heat.append([s.declared_heat_per_area(reference)*piece.area_m2 for s in record.sublayers]
                    if record.volume_convention == 'reference_prism' else
                    [float(u*Fraction(piece.area_m2)) for u in declared_areal_heat(record, reference, budget=budget)])
    initial = sum((Fraction(float(x)) for column in heat for x in column), Fraction(0))
    from . import integration_patch_heat as _patch_heat
    patches = _patch_heat.seed(sphere, tuple((p.face_id, p.cohort_id) for p in sphere.material.pieces()), heat)
    physical = _patch_heat.seed_fields(sphere, by_id, patches, reference, budget=budget)
    return _issued(sphere, records, heat, initial, (), Fraction(0), Fraction(0), reference,
                   patch_heat=patches, physical_columns=physical, budget=budget)


def _check_reference_mass(record, piece, ratios, phases, intervals, *, budget=None):
    """sum(rho_ref t) A per phase must equal the piece's I03 mass within inventory_bound(intervals) relative: P1's own
    guard, its row arithmetic (rho (h0 ratio) A, then fsum) and bound (review basal-02 and RB-2, 4 October 2026). A
    record admitted at declaration (intervals 0) or a piece admitted at its birth step therefore passes P1 there;
    refused ``incompatible support`` otherwise."""
    from .integration_properties import inventory_bound
    bound = inventory_bound(intervals)
    masses = dict(zip(phases, piece.mass_kg))
    if record.volume_convention != 'reference_prism':
        weights = volume_per_area(record, [s.thickness_m*r for s, r in zip(record.sublayers, ratios)], budget=budget)
        for phase in {s.phase for s in record.sublayers}:
            target = sum((Fraction(s.reference_density_kg_m3)*w*Fraction(piece.area_m2)
                          for s, w in zip(record.sublayers, weights) if s.phase == phase), Fraction(0))
            if abs(target-Fraction(masses[phase])) > Fraction(bound)*abs(Fraction(masses[phase])):
                raise TransportRefused('shell reference density contradicts the I03 material mass',
                                       INCOMPATIBLE, 'reference mass')
        return
    for phase in {s.phase for s in record.sublayers}:
        rows = [s.reference_density_kg_m3*(s.thickness_m*ratio)*piece.area_m2
                for s, ratio in zip(record.sublayers, ratios) if s.phase == phase]
        if abs(math.fsum(rows)-masses[phase]) > bound*abs(masses[phase]):
            raise TransportRefused('the record of %r does not hold piece (%r, %r)\'s I03 %r mass: its reference '
                                   'density contradicts the I03 material' % (record.cohort_id, piece.face_id,
                                                                             piece.cohort_id, phase),
                                   INCOMPATIBLE, 'reference mass')


def bound_moving(moving, sphere):
    """``moving`` is the I05 state of exactly ``sphere`` (identity, clock and piece order)."""
    if type(moving) is not MovingState or type(sphere) is not _sphere.SphereState:
        raise TransportRefused('a MovingState and its SphereState are required', STALE, 'state')
    if (moving.state_id, moving.material_id, moving.network_id) != (sphere.state_id, sphere.material.material_id,
                                                                   sphere.network.network_id):
        raise TransportRefused('the moving state belongs to another I03 state', STALE, 'state_id')
    return moving


def restore_moving(record, arrays, sphere, *, budget=None):
    """Restore without inventing historical fields; charge parsing to the caller's shared budget."""
    if type(sphere) is not _sphere.SphereState:
        raise TransportRefused('a moving state is restored only beside its I03 SphereState', STALE, 'state')
    from .resources import select_budget
    from . import integration_patch_heat as PH
    if not hasattr(arrays, 'get'):
        raise TransportRefused('stored moving arrays require a name-to-array mapping', MISSING, 'arrays')
    count = 0 if sphere.material.support is None else len(sphere.material.support.patches)
    raw = arrays.get('moving.physical_columns')
    size = 0 if raw is None else np.asarray(raw).nbytes
    # Charge bytes before JSON parsing allocates rows/integers. Rational widths
    # are allowed to grow with exact heating history, within this same budget.
    with select_budget(budget).reserve(PH.restore_workspace(count, size), category='i05-physical-column-restore'):
        return _restore_moving(record, arrays, sphere, budget=budget)


def _restore_moving(record, arrays, sphere, *, budget):
    """Rebuild a stored moving state through its constructors; its identity must reproduce, and the stored moving
    arrays must be exactly the rebuilt ones, byte for byte, with no other moving array (restore_sphere's exclusive
    check): an edit is refused, never sliced away."""
    if type(sphere) is not _sphere.SphereState:
        raise TransportRefused('a moving state is restored only beside its I03 SphereState', STALE, 'state')
    from .resources import MemoryLimitError
    try:
        schema = record.get('schema') if type(record) is dict else None
        if schema not in (LEGACY_SCHEMA, PATCH_SCHEMA, SCHEMA, RADIAL_SCHEMA):
            raise TransportRefused('unsupported moving-state schema %r; no implicit migration' % (schema,), STALE,
                                   'schema')
        cohorts = tuple(CohortRecord.from_record(row) for row in _sphere._unpack(arrays['moving.cohorts'], 'cohorts'))
        offsets, values = np.asarray(arrays['moving.heat_offsets']), np.asarray(arrays['moving.heat_j'])
        if offsets.dtype != np.int64 or values.dtype != np.float64 or offsets.ndim != 1 or values.ndim != 1:
            raise TransportRefused('the stored heat arrays are not well formed', MISSING, 'heat')
        heat = [values[offsets[i]:offsets[i+1]].tolist() for i in range(len(offsets)-1)]
        accounts = record['accounts']
        initial = _exact(accounts['initial'], 'initial heat')
        supplied = tuple((name, _exact(value, 'supplied heat')) for name, value in accounts['supplied'].items())
        rounding, allowance = _exact(accounts['rounding'], 'heat rounding'), _exact(accounts['allowance'], 'allowance')
        stored_bound = record['lateral_omission_error_k']
        lateral_error = (None if stored_bound == UNKNOWN_BOUND
                         else _exact(stored_bound, 'lateral omission bound'))
        patch_heat = None
        if schema in (PATCH_SCHEMA, SCHEMA, RADIAL_SCHEMA):
            from . import integration_patch_heat as _patch_heat
            patch_heat = _patch_heat.restore(_sphere._unpack(arrays['moving.patch_heat'], 'patch heat'))
        sizes = {r.cohort_id: len(r.sublayers) for r in cohorts}
        physical = None if schema not in (SCHEMA, RADIAL_SCHEMA) else _patch_heat.field_restore(
            _sphere._unpack(arrays['moving.physical_columns'], 'physical columns'),
            expected={p.patch_id: sizes[p.cohort_id] for p in sphere.material.support.patches}, budget=budget)
        state = _issued(sphere, cohorts, heat, initial, supplied, rounding, allowance, record['enthalpy_reference_k'],
                        lateral_error, record['declared_step'], patch_heat=patch_heat, legacy=schema == LEGACY_SCHEMA,
                        physical_columns=physical, budget=budget)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, LedgerError, TectonicsError) as exc:
        if isinstance(exc, (TransportRefused, MemoryLimitError)):
            raise
        raise TransportRefused('the stored moving state is incomplete: '+str(exc), MISSING, 'record') from exc
    if state.moving_id != record.get('moving_id') or state.descriptor() != dict(record):
        raise TransportRefused('the stored moving state does not reproduce its record and identity: edited or '
                               'foreign', STALE, 'moving_id')
    expected = state.arrays()
    kept = {name: np.asarray(array) for name, array in arrays.items() if name.startswith('moving.')}
    if set(kept) != set(expected) or any(
            kept[name].dtype != array.dtype or kept[name].shape != array.shape
            or kept[name].tobytes() != np.ascontiguousarray(array).tobytes() for name, array in expected.items()):
        raise TransportRefused('the stored moving arrays are not those of the rebuilt state: edited or foreign',
                               STALE, 'arrays')
    return state


# ----------------------------------------------------------------------------- the interval declaration

@dataclass(frozen=True)
class Conduction:
    """How heat is conducted over the interval, declared by the caller; never switched automatically (R-3).

    ``lateral`` is 'solve' (explicit flux over admitted contacts; ``nodes`` declares one node direction per face) or
    'omit' (needs ``certificate``: the MC-06 windows and allowance whose exact admission must pass on the state's own
    cells and contacts, on fixed contact geometry only). ``substeps`` is the declared number of explicit lateral
    substeps within the interval. The certificate is captured at construction as canonical JSON text (finite numbers,
    text, lists and objects only), so a later edit of the caller's object cannot reach the declaration or its identity;
    ``declared_certificate()`` returns a fresh copy.

    ``patch_nodes`` supplies actual retained material nodes instead of face
    nodes. The two representations are mutually exclusive; patch conduction
    never infers contacts or temperature from reporting means.
    """
    lateral: str
    nodes: tuple = ()
    certificate: object = None
    substeps: int = 1
    patch_nodes: tuple = ()

    def __post_init__(self):
        if self.lateral not in ('solve', 'omit'):
            raise TransportRefused("the lateral mode is 'solve' or 'omit', declared", MISSING, 'lateral')
        if type(self.substeps) is not int or not 1 <= self.substeps <= _state.MAX_STEPS:
            raise TransportRefused('1 to %d declared lateral substeps' % _state.MAX_STEPS, MISSING, 'substeps')
        try:
            nodes = tuple(sorted((_text(face, 'node face'), tuple(_number(x, 'node direction') for x in direction))
                                 for face, direction in self.nodes)) if type(self.nodes) in (tuple, list) else None
        except (TypeError, ValueError) as exc:
            raise TransportRefused('nodes are (face, direction) pairs, one per face', MISSING, 'nodes') from exc
        if nodes is None or any(len(d) != 3 for _, d in nodes) or len({f for f, _ in nodes}) != len(nodes):
            raise TransportRefused('nodes are (face, direction) pairs, one per face', MISSING, 'nodes')
        if any(not 0 < math.hypot(*d) < math.inf for _, d in nodes):
            raise TransportRefused('a node direction is a finite nonzero vector', MISSING, 'nodes')
        object.__setattr__(self, 'nodes', nodes)
        if type(self.patch_nodes) not in (tuple, list):
            raise TransportRefused('patch nodes are a bounded sequence of pairs', MISSING, 'patch_nodes')
        try:
            patch_nodes = tuple(sorted((_text(p, 'thermal patch'),
                                        tuple(_number(x, 'patch node direction') for x in d))
                                       for p, d in self.patch_nodes))
        except (TypeError, ValueError) as exc:
            raise TransportRefused('patch nodes are (patch_id, direction) pairs', MISSING, 'patch_nodes') from exc
        if (any(len(d) != 3 or not 0 < math.hypot(*d) < math.inf for _, d in patch_nodes)
                or len({p for p, _ in patch_nodes}) != len(patch_nodes)):
            raise TransportRefused('patch nodes require one finite nonzero direction per patch', MISSING,
                                   'patch_nodes')
        if patch_nodes and nodes:
            raise TransportRefused('face and patch thermal nodes are mutually exclusive', INCOMPATIBLE, 'nodes')
        object.__setattr__(self, 'patch_nodes', patch_nodes)
        if self.lateral == 'omit' and self.certificate is None:
            raise TransportRefused('omitting lateral conduction needs an MC-06 certificate', MISSING, 'certificate')
        if self.certificate is not None:
            object.__setattr__(self, 'certificate', _certificate_text(self.certificate))

    def declared_certificate(self):
        """A fresh copy of the captured certificate, or None."""
        return None if self.certificate is None else json.loads(self.certificate)

    def record(self):
        out = dict(lateral=self.lateral, nodes=[[f, list(d)] for f, d in self.nodes],
                   certificate=self.declared_certificate(), substeps=self.substeps)
        if self.patch_nodes:
            out['patch_nodes'] = [[p, list(d)] for p, d in self.patch_nodes]
        return out


def _driving_text(record):
    """Canonical JSON text of an I04 driving record, captured once (finite plain data only)."""
    try:
        return _certificate_text(record)
    except TransportRefused as exc:
        raise TransportRefused('the driving record must be plain data: '+str(exc), MISSING, 'driving') from None


def _certificate_text(certificate):
    """Canonical JSON text of a certificate: plain data with finite numbers only, captured once."""
    def plain(value):
        if value is None or type(value) in (bool, int, str):
            return
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError('non-finite number')
            return
        if type(value) in (list, tuple):
            for item in value:
                plain(item)
            return
        if type(value) is dict and all(type(key) is str for key in value):
            for item in value.values():
                plain(item)
            return
        raise ValueError('not plain data: %r' % type(value).__name__)
    try:
        plain(certificate)
        return json.dumps(certificate, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise TransportRefused('the MC-06 certificate must be plain data (finite numbers, text, lists and objects): '
                               + str(exc), MISSING, 'certificate') from exc


@dataclass(frozen=True)
class MovingAdvance:
    """The I05 declaration for one interval, carried among a commit's transfers as the Motion is.

    ``births`` maps each ridge supply's history reference to its BirthColumn. ``conduction`` is None (advection only
    over this interval, declared and recorded) or a Conduction. ``increments`` gives raw plastic history increments
    (P6) per endpoint piece (face, cohort) and sublayer; every piece of a cohort named must be given, and they must be
    equal within the cohort (split first otherwise).

    ``driving`` (I04.4) is the interval's D1/D2 provenance record, produced and read only by I04
    (integration_feedback): plain data captured once as canonical JSON text, bound into ``advance_id`` and stored with
    the commit. I05 never interprets it. It is emitted only when present, so every advance without one keeps its
    record and identity.

    ``mechanical_energy_j`` declares uniform areal deposition on endpoint
    pieces; ``mechanical_patch_energy_j`` instead names each actual endpoint
    patch. They are mutually exclusive integrated sensible-heat inputs, not a
    conversion of unspecified work or an instruction to heat exported material.
    """
    start_step: int
    end_step: int
    births: tuple = ()
    conduction: object = None
    increments: tuple = ()
    driving: object = None
    mechanical_energy_j: tuple = ()
    mechanical_patch_energy_j: tuple = ()
    advance_id: str = field(init=False)

    def __post_init__(self):
        steps = (self.start_step, self.end_step)
        if any(type(s) is not int for s in steps) or not 0 <= self.start_step < self.end_step <= _state.MAX_STEPS:
            raise TransportRefused('a moving advance declares its interval as whole global steps', MISSING,
                                   'interval')
        if type(self.births) not in (tuple, list) or any(type(pair) not in (tuple, list) or len(pair) != 2
                                                         or type(pair[1]) is not BirthColumn for pair in self.births):
            raise TransportRefused('births are (history_id, BirthColumn) pairs', MISSING, 'births')
        births = tuple(sorted((_text(h, 'birth history'), column) for h, column in self.births))
        if len({h for h, _ in births}) != len(births):
            raise TransportRefused('one birth column per history reference', INCOMPATIBLE, 'births')
        if self.conduction is not None and type(self.conduction) is not Conduction:
            raise TransportRefused('conduction is None (advection only) or a Conduction', MISSING, 'conduction')
        if type(self.increments) not in (tuple, list):
            raise TransportRefused('increments are ((face, cohort), values) pairs', MISSING, 'increments')
        increments = []
        for pair in self.increments:
            if (type(pair) not in (tuple, list) or len(pair) != 2 or type(pair[0]) not in (tuple, list)
                    or len(pair[0]) != 2 or type(pair[1]) not in (tuple, list) or not pair[1]):
                raise TransportRefused('increments are ((face, cohort), values) pairs with one value per sublayer',
                                       MISSING, 'increments')
            key, values = pair
            face, cohort = (_text(key[0], 'increment face'), _text(key[1], 'increment cohort'))
            values = tuple(_number(v, 'kappa increment')+0. for v in values)          # minus zero is zero
            if any(v < 0 for v in values):
                raise TransportRefused('a negative raw-history increment while h = 0', UNSUPPORTED,
                                       'negative increment')
            increments.append(((face, cohort), values))
        increments.sort()
        if len({k for k, _ in increments}) != len(increments):
            raise TransportRefused('one increment per piece', INCOMPATIBLE, 'increments')
        object.__setattr__(self, 'births', births)
        object.__setattr__(self, 'increments', tuple(increments))
        if type(self.mechanical_energy_j) not in (tuple, list):
            raise TransportRefused('mechanical energies are ((face, cohort), layer joules) pairs', MISSING,
                                   'mechanical_energy_j')
        energies = []
        for pair in self.mechanical_energy_j:
            if (type(pair) not in (tuple, list) or len(pair) != 2 or type(pair[0]) not in (tuple, list)
                    or len(pair[0]) != 2 or type(pair[1]) not in (tuple, list) or not pair[1]):
                raise TransportRefused('mechanical energies need a piece key and top-down layer joules', MISSING,
                                       'mechanical_energy_j')
            key, values = pair
            key = (_text(key[0], 'mechanical heat face'), _text(key[1], 'mechanical heat cohort'))
            values = tuple(_number(v, 'mechanical energy')+0. for v in values)
            if any(v < 0 for v in values):
                raise TransportRefused('dissipative heat is nonnegative', UNSUPPORTED, 'mechanical_energy_j')
            energies.append((key, values))
        energies.sort()
        if len({key for key, _ in energies}) != len(energies):
            raise TransportRefused('one mechanical source per piece', INCOMPATIBLE, 'mechanical_energy_j')
        object.__setattr__(self, 'mechanical_energy_j', tuple(energies))
        if type(self.mechanical_patch_energy_j) not in (tuple, list):
            raise TransportRefused('patch energies are (patch_id, layer joules) pairs', MISSING,
                                   'mechanical_patch_energy_j')
        patch_energies = []
        for pair in self.mechanical_patch_energy_j:
            if (type(pair) not in (tuple, list) or len(pair) != 2
                    or type(pair[1]) not in (tuple, list) or not pair[1]):
                raise TransportRefused('patch energies need an identity and top-down layer joules', MISSING,
                                       'mechanical_patch_energy_j')
            key, values = pair
            key = _text(key, 'mechanical heat patch')
            values = tuple(_number(v, 'patch mechanical energy', nonnegative=True)+0. for v in values)
            patch_energies.append((key, values))
        patch_energies.sort()
        if len({key for key, _ in patch_energies}) != len(patch_energies):
            raise TransportRefused('one mechanical source per patch', INCOMPATIBLE, 'mechanical_patch_energy_j')
        if energies and patch_energies:
            raise TransportRefused('piece and patch sources are mutually exclusive', INCOMPATIBLE,
                                   'mechanical_patch_energy_j')
        object.__setattr__(self, 'mechanical_patch_energy_j', tuple(patch_energies))
        if self.driving is not None:
            if type(self.driving) is not dict:
                raise TransportRefused('the driving record is a plain dict produced by I04', MISSING, 'driving')
            object.__setattr__(self, 'driving', _driving_text(self.driving))
        object.__setattr__(self, 'advance_id', hashlib.sha256(_json(self._declared())).hexdigest())

    def declared_driving(self):
        """A fresh copy of the captured I04 driving record, or None."""
        return None if self.driving is None else json.loads(self.driving)

    def _declared(self):
        out = dict(schema=ADVANCE_SCHEMA, start_step=self.start_step, end_step=self.end_step,
                   births=[[h, column.record()] for h, column in self.births],
                   conduction=None if self.conduction is None else self.conduction.record(),
                   increments=[[list(key), list(values)] for key, values in self.increments])
        if self.driving is not None:
            out['driving'] = self.declared_driving()
        if self.mechanical_energy_j:
            out['schema'] = HEATED_ADVANCE_SCHEMA
            out['mechanical_energy_j'] = [[list(key), list(values)] for key, values in self.mechanical_energy_j]
        if self.mechanical_patch_energy_j or (self.conduction is not None and self.conduction.patch_nodes):
            out['schema'] = PATCH_ADVANCE_SCHEMA
        if self.mechanical_patch_energy_j:
            out['mechanical_patch_energy_j'] = [[key, list(values)] for key, values in self.mechanical_patch_energy_j]
        if any(column.volume_convention != 'reference_prism' for _, column in self.births):
            out['schema'] = RADIAL_ADVANCE_SCHEMA
        return out

    def record(self):
        return dict(self._declared(), advance_id=self.advance_id)

    @staticmethod
    def from_record(row):
        try:
            conduction = row['conduction']
            if conduction is not None:
                conduction = Conduction(conduction['lateral'], tuple((f, tuple(d)) for f, d in conduction['nodes']),
                                        conduction['certificate'], conduction['substeps'],
                                        tuple((p, tuple(d)) for p, d in conduction.get('patch_nodes', ())))
            advance = MovingAdvance(row['start_step'], row['end_step'],
                                    tuple((h, BirthColumn.from_record(c)) for h, c in row['births']), conduction,
                                    tuple((tuple(k), tuple(v)) for k, v in row['increments']), row.get('driving'),
                                    tuple((tuple(k), tuple(v)) for k, v in row.get('mechanical_energy_j', ())),
                                    tuple((k, tuple(v)) for k, v in row.get('mechanical_patch_energy_j', ())))
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
            raise TransportRefused('the stored moving advance is incomplete', MISSING, 'advance') from exc
        if row.get('schema') not in (ADVANCE_SCHEMA, HEATED_ADVANCE_SCHEMA, PATCH_ADVANCE_SCHEMA, RADIAL_ADVANCE_SCHEMA) or _json(advance.record()) != _json(dict(row)):
            raise TransportRefused('the stored moving advance does not reproduce its record', STALE, 'advance_id')
        return advance


# ----------------------------------------------------------------------------- transport over the step's rows

def _moved_face_ids(sphere, step, budget):
    """The face IDs the motion rows' receivers index: the moved network, before any mesh change and events."""
    if step.map._mesh is None:
        return step.state.network.face_ids              # events keep every face and its order
    motion = step.motion
    geometry = _transfer._moved(sphere.network, motion, None, None, budget)
    moved = _transfer._issued(sphere.network, geometry, step.state.network.time_s, motion.end_step, None, budget,
                              None)
    if moved.atlas.geometry_id != step.map.moved_geometry_id:
        raise TransportRefused('the moved geometry does not reproduce the map it was measured on', STALE,
                               'moved_geometry_id')
    return moved.face_ids


def _consumed(boundary_id, values, book, sinks):
    sink = sinks.get(boundary_id)
    if sink is None:
        raise TransportRefused('trench %r consumes material but declares no destination' % boundary_id, MISSING,
                               boundary_id)
    amount = sum(values, Fraction(0))
    for destination, fraction, _ in sink.destinations:
        book(destination, -amount*Fraction(fraction))


def _born(step, columns_by_history, reference, book, sinks, *, budget=None):
    """Born pieces' exact sublayer heat per birth row (receivers index the moved network) and the born cohorts'
    records; a transient birth, consumed within the interval, is booked in and out at once."""
    supplies = {'ridge|%s|%s' % (s.boundary_id, s.side): s for s in step.motion.supplies}
    rows = step.map._motion
    pieces, records = [], {}
    births = sorted(step.summary()['births'], key=lambda r: r['party'])
    unused = set(columns_by_history)-{supplies[record['party']].history_id for record in births}
    if unused:
        raise TransportRefused('birth column %r is declared for no birth of this step: an unused declaration is '
                               'refused, never ignored' % sorted(unused)[0], INCOMPATIBLE, 'births')
    for record in births:
        party = record['party']
        supply = supplies[party]
        column = columns_by_history.get(supply.history_id)
        if column is None:
            raise TransportRefused('the birth of %r has no birth column for its history reference %r'
                                   % (party, supply.history_id), MISSING, 'births')
        _check_birth(column, supply, budget=budget)
        if column.volume_convention != 'reference_prism' and column.reference_radius_m != step.state.network.sphere.radius_m:
            raise TransportRefused('birth shell radius differs from actual sphere', STALE, 'reference_radius_m')
        # Birth accounts retain their existing dyadic per-area source convention;
        # the exact shell-caloric representation residual is carried separately.
        per_area = [Fraction(float(u)) for u in declared_areal_heat(column, reference, budget=budget)]
        cohort = record['cohort_id']
        records[cohort] = birth_record(cohort, column)
        index = rows.parties.index(party)
        for row in range(len(rows.donor)):
            if rows.donor[row] < 0 and rows.party[row] == index:
                values = [h*Fraction(rows.area_m2[row]) for h in per_area]
                book(party, sum(values, Fraction(0)))
                pieces.append(((rows.receiver[row], cohort), values))
        for birth_party, sink_party, area in rows.transient:
            if birth_party == index:
                values = [h*Fraction(area) for h in per_area]
                book(party, sum(values, Fraction(0)))
                trench = rows.parties[sink_party]
                _consumed(trench[len('trench|'):], values, book, sinks)
    return pieces, records


def _check_birth(column, supply, *, budget=None):
    """The birth column reproduces its supply: per phase its thickness within I03's tolerance, and its mass per area
    within inventory_bound(0), no wider than P1's guard at declaration (RB-2, 4 October 2026; it was 4(n+2) eps). Each
    born piece is then checked by P1's own guard at its birth step (advance_moving)."""
    from .integration_properties import inventory_bound
    thickness, mass = dict(supply.thickness_m), dict(supply.mass_per_area_kg_m2)
    phases = {s.phase for s in column.sublayers}
    if not phases <= set(thickness) or any(h != 0 for p, h in thickness.items() if p not in phases):
        raise TransportRefused('the birth column of %r represents other phases than its supply' % supply.history_id,
                               INCOMPATIBLE, 'births')
    for phase in phases:
        weights = volume_per_area(column, budget=budget)
        h = (math.fsum(s.thickness_m for s in column.sublayers if s.phase == phase)
             if column.volume_convention == 'reference_prism' else
             float(sum((w for s, w in zip(column.sublayers, weights) if s.phase == phase), Fraction(0))))
        m = (math.fsum(s.reference_density_kg_m3*s.thickness_m for s in column.sublayers if s.phase == phase)
             if column.volume_convention == 'reference_prism' else
             float(sum((Fraction(s.reference_density_kg_m3)*w for s, w in zip(column.sublayers, weights)
                        if s.phase == phase), Fraction(0))))
        if (abs(h-thickness[phase]) > _sphere.RELATIVE_TOLERANCE*thickness[phase]
                or abs(m-mass[phase]) > inventory_bound(0)*mass[phase]):
            raise TransportRefused("the birth column of %r does not reproduce its supply's %r thickness and mass"
                                   % (supply.history_id, phase), INCOMPATIBLE, 'births')


def _transported(parent, sphere, step, advance, budget):
    """(cohort records, exact heat per endpoint (face, cohort), supplied bookings) after the step's rows, births,
    events and history splits. Nothing is averaged: rows divide each sublayer exactly as I03 divides its accounts."""
    motion = step.motion
    from . import integration_support as _support
    from . import integration_patch_heat as _patch_heat
    _support.required(sphere.material)
    if parent._patch_heat is None:
        raise TransportRefused('historical piece heat has no patch allocation; declare positioned initial '
                               'columns rather than inventing mixed saved state', UNSUPPORTED, 'patch_heat')
    if parent._physical_columns is None:
        raise TransportRefused('historical heat has no retained physical column; no implicit reconstruction '
                               'from rounded extensive accounts', UNSUPPORTED, 'physical_columns')
    if motion.regional_returns:
        raise TransportRefused('a regional return moves material without rows: per-piece I05 content cannot follow '
                               'it (an I07 requirement)', UNSUPPORTED, 'regional_returns')
    supplied = dict(parent._supplied)

    def book(name, amount):
        supplied[name] = supplied.get(name, Fraction(0))+amount
    network = sphere.network
    columns = dict(parent._patch_heat)
    records = {r.cohort_id: r for r in parent.cohorts}
    sinks = {s.boundary_id: s for s in motion.sinks}
    born, new_records = _born(step, dict(advance.births), parent.enthalpy_reference_k, book, sinks, budget=budget)
    records.update(new_records)
    moved_ids = _moved_face_ids(sphere, step, budget)
    moved = _patch_heat.routed(columns, step._patch_routes[0], book, sinks)
    physical = _patch_heat.route_fields(dict(parent._physical_columns), columns, step._patch_routes[0],
                                         step._motion_material.support.patches)
    for (target, cohort), values in born:
        patches = step._motion_material.support.patches_of_piece(moved_ids[target], cohort)
        areas = [p.stock[0] for p in patches]
        divided = [_transfer._split(v, areas, sum(areas, Fraction(0)), _transfer._largest(areas)) for v in values]
        for j, patch in enumerate(patches):
            if patch.patch_id in moved:
                raise TransportRefused('birth heat duplicates a retained position', UNRESOLVED, 'patch_heat')
            moved[patch.patch_id] = tuple(column[j] for column in divided)
        physical.update(_patch_heat.birth_fields(records[cohort], patches, values, parent.enthalpy_reference_k,
                                                 budget=budget))
    endpoint_ids = step.state.network.face_ids
    if step.map._mesh is not None:
        final_patches = {p.patch_id: p for p in step.state.material.support.patches}
        before_relabel = {source: final_patches[target] for source, target in step._patch_routes[2]}
        physical = _patch_heat.route_fields(physical, moved, step._patch_routes[1], before_relabel)
        moved = _patch_heat.routed(moved, step._patch_routes[1], book, sinks)
    result = {target: moved[source] for source, target in step._patch_routes[2]}
    physical = {target: physical[source] for source, target in step._patch_routes[2]}
    if set(moved) != {source for source, _ in step._patch_routes[2]}:
        raise TransportRefused('patch relabelling loses a thermal position', UNRESOLVED, 'patch_heat')
    # History splits relabel named endpoint pieces; a sub-cohort's record copies its parent's, never averaged.
    for split in motion.history_splits:
        for history, faces in split.groups:
            child = _splits.sub_cohort_id(split.cohort_id, motion.end_step, history)
            records[child] = records[split.cohort_id].renamed(child)
    return records, result, supplied, set(new_records), physical


def _patch_column(moving, sphere, patch_id):
    """Actual positioned column: (patch Piece allocation, cohort record, thickness, temperature)."""
    from .integration_patch_heat import column
    return column(moving, sphere, patch_id)


def _patch_columns(moving, sphere, patch_ids):
    """Batch local columns for boundary/strength adapters, keyed by patch identity."""
    from .integration_patch_heat import columns
    return columns(moving, sphere, patch_ids)


@dataclass(frozen=True)
class MovingStep:
    """One I05 transaction: the successor moving state and what it did (``summary``)."""
    state: MovingState
    advance: MovingAdvance
    summary: dict


def _bound_driving(record, sphere, step):
    """Commit-time binding of an I04 driving record (ruling P2(e)), on every commit path: its parent, endpoint and
    motion are this step's, and its interval (start_step, end_step, start_s, end_s) is this step's, field by field. The
    record is not interpreted further here; I04 replays it on reopen."""
    try:
        interval = record['interval']
        checks = (('parent_state_id', record['parent_state_id'] == sphere.state_id),
                  ('endpoint_state_id', record['endpoint_state_id'] == step.state.state_id),
                  ('motion_id', record['motion_id'] == step.motion.motion_id),
                  ('interval', len(interval) == 4 and int(interval[0]) == step.motion.start_step
                   and int(interval[1]) == step.motion.end_step and float(interval[2]) == sphere.network.time_s
                   and float(interval[3]) == step.state.network.time_s))
    except (KeyError, TypeError, ValueError, IndexError):
        raise TransportRefused('the driving record lacks its binding fields', MISSING, 'driving') from None
    for name, ok in checks:
        if not ok:
            raise TransportRefused('the driving record is not bound to this step (%s)' % name, STALE, name)


def advance_moving(parent, sphere, step, advance, *, budget=None):
    """Advance physical patch columns and their exact accounts over the accepted material routes."""
    bound_moving(parent, sphere)
    if type(step) is not _transfer.Step or step.parent_state_id != sphere.state_id:
        raise TransportRefused('the I03 step does not continue this state', STALE, 'parent_state_id')
    if type(advance) is not MovingAdvance:
        raise TransportRefused('a MovingAdvance declares the interval', MISSING, 'advance')
    from .resources import select_budget
    from . import integration_patch_heat as PH
    sizes = {r.cohort_id: len(r.sublayers) for r in parent.cohorts}
    maximum = max([*sizes.values(), *(len(b.sublayers) for _, b in advance.births)])
    count = sum(len(column[0]) for _, column in (parent._physical_columns or ()))
    count += sum(sizes.get(p.cohort_id, maximum) for p in step.state.material.support.patches)
    count += sum(sizes.get(p.cohort_id, maximum) for p in step._motion_material.support.patches)
    existing = dict(parent._physical_columns or ())
    with select_budget(budget).reserve(PH.field_workspace(existing)+16384*count,
                                       category='i05-physical-column-advance'):
        return _advance_moving(parent, sphere, step, advance, budget=budget)


def _advance_moving(parent, sphere, step, advance, *, budget=None):
    """The I05 successor of ``parent`` over the accepted I03 ``step``; nothing is published here.

    ``sphere`` is the parent's I03 state. Transport follows the step's own rows (never rows inferred from geometry);
    then, if declared, conduction over the interval on the endpoint pieces (integration_thermal), booked to its own
    party with its energy closure checked; then the raw-history increments, uniform within each cohort. A refusal
    leaves the parent untouched.
    """
    bound_moving(parent, sphere)
    if type(step) is not _transfer.Step or step.parent_state_id != sphere.state_id:
        raise TransportRefused('the I03 step does not continue this state', STALE, 'parent_state_id')
    if type(advance) is not MovingAdvance:
        raise TransportRefused('a MovingAdvance declares the interval', MISSING, 'advance')
    if (advance.start_step, advance.end_step) != (step.motion.start_step, step.motion.end_step):
        raise TransportRefused('the moving advance declares another interval than the step', STALE, 'interval')
    if advance.driving is not None:
        _bound_driving(advance.declared_driving(), sphere, step)
    records, result, supplied, born, physical = _transported(parent, sphere, step, advance, budget)
    from . import integration_patch_heat as _patch_heat
    from . import integration_support as _support
    endpoint = step.state
    pieces = tuple((p.face_id, p.cohort_id) for p in endpoint.material.pieces())
    patches_of = {key: endpoint.material.support.patches_of_piece(*key) for key in pieces}
    mechanical = None
    patch_mechanical = None
    mechanical_total = Fraction(0)
    physical_sources = {}
    source_bounds = {}
    if advance.mechanical_energy_j:
        from . import integration_thermal as _thermal
        mechanical = dict(advance.mechanical_energy_j)
        sources = _thermal._mechanical_sources(endpoint.material.pieces(), records, mechanical)
        mechanical_total = sum((Fraction(float(v)) for column in sources for v in column), Fraction(0))
        if advance.conduction is None or advance.conduction.patch_nodes:
            patch_mechanical = {}
            for piece, energy in zip(pieces, sources):
                # This input declares uniform areal deposition over its endpoint
                # piece. It does not claim a spatially localised shear source.
                patches = patches_of[piece]
                areas = [p.stock[0] for p in patches]
                parts = [_transfer._split(Fraction(float(q)), areas, sum(areas, Fraction(0)),
                                          _transfer._largest(areas)) for q in energy]
                bounds = [_patch_heat.split_bounds(Fraction(float(q)), areas) for q in energy]
                for j, patch in enumerate(patches):
                    patch_mechanical[patch.patch_id] = tuple(column[j] for column in parts)
                    physical_sources[patch.patch_id] = tuple(Fraction(float(q))/sum(areas, Fraction(0)) for q in energy)
                    source_bounds[patch.patch_id] = tuple(row[j] for row in bounds)
            if advance.conduction is None:
                for key, column in patch_mechanical.items():
                    result[key] = tuple(value+source for value, source in zip(result[key], column))
                    patch = next(p for p in endpoint.material.support.patches if p.patch_id == key)
                    physical[key] = _patch_heat.add_energy(physical[key], patch.stock[0], column,
                        areal=physical_sources[key], rounding_bound=source_bounds[key])
        supplied[MECHANICAL_HEAT_PARTY] = supplied.get(MECHANICAL_HEAT_PARTY, Fraction(0))+mechanical_total
    if advance.mechanical_patch_energy_j:
        patch_mechanical = {key: tuple(Fraction(v) for v in values)
                            for key, values in advance.mechanical_patch_energy_j}
        if any(key not in result or len(values) != len(result[key]) for key, values in patch_mechanical.items()):
            raise TransportRefused('patch source needs an endpoint patch and its full layer column', MISSING,
                                   'mechanical_patch_energy_j')
        mechanical_total = sum((v for column in patch_mechanical.values() for v in column), Fraction(0))
        if advance.conduction is None:
            for key, column in patch_mechanical.items():
                result[key] = tuple(value+source for value, source in zip(result[key], column))
                patch = next(p for p in endpoint.material.support.patches if p.patch_id == key)
                physical[key] = _patch_heat.add_energy(physical[key], patch.stock[0], column)
        elif not advance.conduction.patch_nodes:
            raise TransportRefused('patch heating with conduction requires explicit patch thermal nodes',
                                   UNSUPPORTED, 'patch conduction')
        supplied[MECHANICAL_HEAT_PARTY] = supplied.get(MECHANICAL_HEAT_PARTY, Fraction(0))+mechanical_total
    patch_heat = result
    heat, _ = _patch_heat.project(endpoint, patch_heat)
    rounding, allowance = parent._rounding, parent._allowance
    for cohort in endpoint.material.cohorts:
        if cohort.cohort_id not in records:
            raise TransportRefused('cohort %r of the endpoint has no record' % cohort.cohort_id, MISSING,
                                   cohort.cohort_id)
    for piece in endpoint.material.pieces():            # a born piece passes P1's guard at its birth step (RB-2)
        if piece.cohort_id in born:
            record = records[piece.cohort_id]
            _check_reference_mass(record, piece, _thickness_ratios(record, piece, endpoint.material.phases, budget=budget),
                                  endpoint.material.phases, endpoint.network.step-parent.declared_step, budget=budget)
    summary = dict(advance_id=advance.advance_id, map_id=step.map.map_id, parent_state_id=step.parent_state_id,
                   state_id=endpoint.state_id, transport='exact over retained material patch routes',
                   conduction='none declared: advection only over this interval', increments=None)
    lateral_error = parent._lateral_error
    if advance.conduction is None:                     # no conduction: off the column-only trajectory, so UNKNOWN
        lateral_error = None
    elif advance.conduction.patch_nodes:
        from . import integration_thermal as _thermal
        before = sum((value for column in patch_heat.values() for value in column), Fraction(0))
        patch_heat, report = _thermal.conducted_patches(endpoint, records, patch_heat,
            parent.enthalpy_reference_k, sphere, step, advance.conduction, budget,
            carried=lateral_error, mechanical_patch_energy_j=patch_mechanical, physical_columns=physical,
            physical_source_areal=physical_sources)
        physical = _patch_heat.field_restore(report.pop('physical_columns'), budget=budget)
        after = sum((value for column in patch_heat.values() for value in column), Fraction(0))
        supplied[CONDUCTION_PARTY] = supplied.get(CONDUCTION_PARTY, Fraction(0))+(after-before)-mechanical_total
        heat, _ = _patch_heat.project(endpoint, patch_heat)
        summary['conduction'] = report
        # A resolved lateral solve does not certify a future omission window.
        lateral_error = None
    else:
        from . import integration_thermal as _thermal
        physical_pieces = {}
        if any(len(patches) != 1 for patches in patches_of.values()):
            # Preserve the established topology and omission refusals before
            # checking whether a numerical node represents one actual column.
            if advance.conduction.lateral != 'solve' and not _thermal._fixed_geometry(sphere, step):
                raise _thermal.ThermalRefused('omitting lateral conduction is admitted only over fixed contact '
                                              'geometry (MC-06)', 'unsupported', 'omit')
            _thermal._contacts(endpoint, records, advance.conduction, budget=budget)
            for key, patches in patches_of.items():
                columns = [physical[p.patch_id][:2] for p in patches]
                if any(column != columns[0] for column in columns[1:]):
                    raise TransportRefused('different retained patch columns require explicit thermal contact '
                                           'nodes and conductances; a piece mean is not admitted', UNSUPPORTED,
                                           'patch conduction')
        physical_pieces = {key: physical[patches[0].patch_id][:2] for key, patches in patches_of.items()}
        old_heat = heat
        before = sum((Fraction(x) for column in heat for x in column), Fraction(0))
        heat, report = _thermal.conducted(endpoint, records, heat, parent.enthalpy_reference_k, sphere, step,
                                          advance.conduction, budget, carried=lateral_error,
                                          mechanical_energy_j=mechanical, physical_columns=physical_pieces)
        physical_out = {tuple(key): tuple(_patch_heat._rational(q) for q in values)
                        for key, values in report.pop('physical_energy_areal')}
        after = sum((Fraction(x) for column in heat for x in column), Fraction(0))
        supplied[CONDUCTION_PARTY] = supplied.get(CONDUCTION_PARTY, Fraction(0))+(after-before)-mechanical_total
        for key, old, new in zip(pieces, old_heat, heat):
            patches = patches_of[key]
            allocated = {p.patch_id: [Fraction(0)]*len(old) for p in patches}
            operation_bounds = {p.patch_id: [Fraction(0)]*len(old) for p in patches}
            for layer, (a, b) in enumerate(zip(old, new)):
                areas = [p.stock[0] for p in patches]
                change = _transfer._split(Fraction(b)-Fraction(a), areas, sum(areas, Fraction(0)),
                                           _transfer._largest(areas))
                bounds = _patch_heat.split_bounds(Fraction(b)-Fraction(a), areas)
                for patch, amount, error in zip(patches, change, bounds):
                    values = list(patch_heat[patch.patch_id])
                    values[layer] += amount
                    patch_heat[patch.patch_id] = tuple(values)
                    allocated[patch.patch_id][layer] = amount
                    operation_bounds[patch.patch_id][layer] = (
                        _patch_heat.half_ulp(b)*patch.stock[0]/sum(areas, Fraction(0))+error)
            du = tuple(a-b for a, b in zip(physical_out[key], physical_pieces[key][1]))
            for patch in patches:
                physical[patch.patch_id] = _patch_heat.add_energy(physical[patch.patch_id], patch.stock[0],
                    allocated[patch.patch_id], areal=du, rounding_bound=operation_bounds[patch.patch_id])
        heat, _ = _patch_heat.project(endpoint, patch_heat)
        summary['conduction'] = report
        if report['certificate'] is not None:          # carried as the least binary64 value not below the bound
            lateral_error = Fraction(_thermal._upper_float(Fraction(report['certificate']['error_bound_exact_k'])))
    if mechanical is not None or patch_mechanical is not None:
        summary['mechanical_heat'] = dict(energy_j=float(mechanical_total), energy_exact_j=_exact_text(mechanical_total),
                                          party=MECHANICAL_HEAT_PARTY,
                                          evaluation=('declared integrated source on exact endpoint patches'
                                                      if advance.mechanical_patch_energy_j else
                                                      'declared uniform areal source on endpoint pieces'))
    if advance.increments:
        records, applied = _incremented(records, pieces, advance.increments)
        summary['increments'] = applied
    state = _issued(endpoint, tuple(records[c.cohort_id] for c in endpoint.material.cohorts), heat, parent._initial,
                    tuple(supplied.items()), rounding, allowance, parent.enthalpy_reference_k, lateral_error,
                    parent.declared_step, patch_heat=patch_heat, physical_columns=physical, budget=budget)
    return MovingStep(state, advance, summary)


def _incremented(records, pieces, increments):
    """Commit raw-history increments (P6) once: equal within each cohort, or ``history divergence``."""
    given = dict(increments)
    by_cohort = {}
    for key, values in given.items():
        if key not in pieces:
            raise TransportRefused('an increment names piece %r, which the endpoint does not hold' % (key,),
                                   MISSING, key[0])
        by_cohort.setdefault(key[1], set()).add(values)
    applied = {}
    for cohort, values in sorted(by_cohort.items()):
        held = [key for key in pieces if key[1] == cohort]
        if any(key not in given for key in held):
            raise TransportRefused('every endpoint piece of cohort %r needs its increment' % cohort, MISSING, cohort)
        record = records[cohort]
        if any(len(increment) != len(record.kappa) for increment in values):
            raise TransportRefused('one increment per sublayer of %r' % cohort, MISSING, cohort)
        if len(values) != 1:
            raise TransportRefused('the increments of cohort %r differ between its pieces: split the cohort in this '
                                   'interval first; raw history is never averaged' % cohort, DIVERGENCE, cohort)
        increment = next(iter(values))
        records[cohort] = replace(record, kappa=tuple(k+i for k, i in zip(record.kappa, increment)))
        applied[cohort] = list(increment)
    return records, applied


def split_for_increments(step, increments, *, history_of):
    """The HistorySplits that make raw-history increments uniform within every cohort (the two-pass P6 flow).

    ``step`` is the same interval advanced without splits, and ``increments`` maps its endpoint pieces (face,
    cohort) to their increments. In each cohort the group holding the most pieces (ties: the smallest increment)
    stays in the cohort; every other distinct increment becomes a sub-cohort, whose history reference
    ``history_of(cohort, increment)`` supplies. Increments are grouped by equal values, minus zero being zero, as
    MovingAdvance holds them. Returns (splits, increments renamed to the split pieces).
    """
    given = {tuple(k): tuple(float(v)+0. for v in values) for k, values in dict(increments).items()}
    groups = {}
    for (face, cohort), values in sorted(given.items()):
        groups.setdefault(cohort, {}).setdefault(values, []).append(face)
    splits, renamed = [], dict(given)
    for cohort, by_value in sorted(groups.items()):
        if len(by_value) < 2:
            continue
        keep = min(by_value, key=lambda value: (-len(by_value[value]), value))
        parts = []
        for value, faces in sorted(by_value.items()):
            if value == keep:
                continue
            history = history_of(cohort, value)
            parts.append((history, tuple(faces)))
            child = _splits.sub_cohort_id(cohort, step.motion.end_step, history)
            for face in faces:
                renamed[(face, child)] = renamed.pop((face, cohort))
        splits.append(_splits.HistorySplit(cohort, tuple(parts)))
    return tuple(splits), tuple(sorted(renamed.items()))


# ----------------------------------------------------------------------------- the I02 attachment (ruling I05-1)

STEP_SCHEMA = 'atlas.i05-moving-step.v1'


def step_record(parent, out):
    """What a commit stores for one I05 transaction: the parent's identity, the advance, what it did and the
    successor's descriptor."""
    return dict(schema=STEP_SCHEMA, producer=PRODUCER, parent_moving_id=parent.moving_id,
                moving_id=out.state.moving_id, state_id=out.state.state_id, advance=out.advance.record(),
                summary=out.summary, state=out.state.descriptor())


def proposed(ledger, parent, parent_meta, step, transfers, budget=None):
    """What Ledger.commit calls when a moving state is attached: (the other transfers, the MovingStep).

    Exactly one MovingAdvance must be among ``transfers``, for exactly the step's interval: absent I05 content is
    unknown, never assumed. The parent's moving state and network are the ledger's own restored ones. A refusal is
    the exchange's refusal: nothing of the interval is committed.
    """
    from .integration_ledger import ExchangeRefused
    advances = [item for item in transfers if type(item) is MovingAdvance]
    others = tuple(item for item in transfers if type(item) is not MovingAdvance)
    if len(advances) != 1:
        raise ExchangeRefused('a moving state is attached to this history: each commit carries exactly one '
                              'MovingAdvance for its interval; absent I05 content is unknown, never assumed')
    if step is None:
        raise LedgerError('a moving state moves only with its attached network')
    moving = ledger._restored_moving(parent, parent_meta)
    sphere = ledger._restored_sphere(parent, parent_meta)
    try:
        out = advance_moving(moving, sphere, step, advances[0], budget=budget)
    except TransportRefused as exc:
        raise ExchangeRefused('the moving state refuses this interval: '+str(exc)) from exc
    except TectonicsError as exc:
        raise ExchangeRefused('the moving state refuses this interval: '+str(exc)) from exc
    return others, out


def linked(record, parent_record, sphere_record):
    """Structural check of a successor's stored 'moving' record against its parent's and its network's."""
    try:
        parent = parent_record if parent_record.get('schema') in (LEGACY_SCHEMA, PATCH_SCHEMA, SCHEMA, RADIAL_SCHEMA) else parent_record['state']
        return (record['schema'] == STEP_SCHEMA and record['parent_moving_id'] == parent['moving_id']
                and record['state']['moving_id'] == record['moving_id']
                and record['state']['state_id'] == record['state_id'] == sphere_record['state_id']
                and record['advance']['advance_id'] == record['summary']['advance_id'])
    except (KeyError, TypeError, AttributeError):
        return False


def content(metadata):
    """[('moving', advance identity)] of a stored commit, for the clock's comparison of what it carries."""
    record = metadata.get('moving') if isinstance(metadata, dict) else None
    if not isinstance(record, dict) or record.get('schema') != STEP_SCHEMA:
        return []
    return [('moving', record.get('advance', {}).get('advance_id'))]


def _state_record(record):
    return record if record.get('schema') in (LEGACY_SCHEMA, PATCH_SCHEMA, SCHEMA, RADIAL_SCHEMA) else record['state']


def restored(parent, metadata, arrays, sphere, *, budget=None):
    """Rebuild the moving state of a stored commit by replay.

    ``parent`` is its parent's moving state or (metadata, arrays); ``sphere`` is the parent's I03 state. The parent is
    rebuilt through its constructors, the commit's I03 step is rebuilt and verified (integration_transfer), the stored
    MovingAdvance must reproduce its identity, and the transaction is run again: the stored record and every stored
    moving array must equal the recomputed ones. An edited or foreign record is refused.
    """
    record = metadata['moving']
    if type(parent) is tuple:
        parent = restore_moving(_state_record(parent[0]['moving']), parent[1], sphere)
    if not isinstance(record, dict) or record.get('schema') != STEP_SCHEMA:
        raise LedgerError('unsupported moving step schema; no implicit history migration')
    step, _ = _transfer._restored_step(sphere, metadata, arrays, budget=budget)
    advance = MovingAdvance.from_record(record['advance'])
    out = advance_moving(parent, sphere, step, advance, budget=budget)
    if _json(step_record(parent, out)) != _json(record):
        raise LedgerError('the stored moving step is not reproduced by its parent, step and advance: edited or '
                          'foreign')
    expected = out.state.arrays()
    kept = {name: np.asarray(array) for name, array in arrays.items() if name.startswith('moving.')}
    if set(kept) != set(expected) or any(
            kept[name].dtype != array.dtype or kept[name].shape != array.shape
            or kept[name].tobytes() != np.ascontiguousarray(array).tobytes() for name, array in expected.items()):
        raise LedgerError('the stored moving arrays are not those of the recorded step: edited or foreign')
    return out.state
