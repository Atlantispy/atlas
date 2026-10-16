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

SCHEMA = 'atlas.i05-moving-state.v1'
ADVANCE_SCHEMA = 'atlas.i05-moving-advance.v1'
PRODUCER = 'atlas_tectonics.integration_material'
NOT_REPRESENTED = 'NOT_REPRESENTED'
MAX_SUBLAYERS = 32                       # the I01_GPE / P1 column representation bound
CONDUCTION_PARTY = 'i05|conduction'
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

    def phase_thickness(self, phase):
        return math.fsum(s.thickness_m for s in self.sublayers if s.phase == phase)

    def renamed(self, cohort_id):
        """The same carried content under a sub-cohort's identity (a history split copies, never averages)."""
        return replace(self, cohort_id=cohort_id, bond=replace(self.bond, cohort=cohort_id))

    def record(self):
        return dict(cohort_id=self.cohort_id, profile_id=self.profile_id, thermal_source=self.thermal_source,
                    sublayers=[s.record() for s in self.sublayers],
                    surface_temperature_k=self.surface_temperature_k, base_temperature_k=self.base_temperature_k,
                    cooling_start_s=self.cooling_start_s, kappa=list(self.kappa),
                    bond=dict(ever_broken=self.bond.ever_broken, support=self.bond.support),
                    compaction=self.compaction if self.compaction == NOT_REPRESENTED else self.compaction.record(),
                    elastic=self.elastic if self.elastic == NOT_REPRESENTED else self.elastic.record())

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
                                compaction, memory(row['elastic'], ElasticMemory))
        except (KeyError, TypeError, ValueError, BondRefused) as exc:
            raise TransportRefused('a stored cohort record is incomplete', MISSING, 'cohort record') from exc


def birth_record(cohort_id, column):
    """The record of a cohort born from a supply: its column with zero raw history and the declared bond support."""
    if type(column) is not BirthColumn:
        raise TransportRefused('a birth column is required', MISSING, 'birth column')
    return CohortRecord(cohort_id, column.profile_id, column.thermal_source, column.sublayers,
                        column.surface_temperature_k, column.base_temperature_k, None,
                        (0.,)*len(column.sublayers), BondRecord(cohort_id, False, column.bond_support))


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

    def __post_init__(self):
        record = CohortRecord('birth', self.profile_id, self.thermal_source, self.sublayers,
                              self.surface_temperature_k, self.base_temperature_k, None, (0.,)*len(self.sublayers)
                              if type(self.sublayers) in (tuple, list) else (), BondRecord('birth', False, 'UNKNOWN'))
        object.__setattr__(self, 'sublayers', record.sublayers)
        object.__setattr__(self, 'surface_temperature_k', record.surface_temperature_k)
        object.__setattr__(self, 'base_temperature_k', record.base_temperature_k)
        if self.bond_support not in SUPPORTS:
            raise TransportRefused('a born cohort declares its bond support', MISSING, 'bond_support')

    def record(self):
        return dict(profile_id=self.profile_id, thermal_source=self.thermal_source,
                    sublayers=[s.record() for s in self.sublayers], surface_temperature_k=self.surface_temperature_k,
                    base_temperature_k=self.base_temperature_k, bond_support=self.bond_support)

    @staticmethod
    def from_record(row):
        try:
            return BirthColumn(row['profile_id'], row['thermal_source'], tuple(Sublayer(**s) for s in row['sublayers']),
                               row['surface_temperature_k'], row['base_temperature_k'], row['bond_support'])
        except (KeyError, TypeError, ValueError) as exc:
            raise TransportRefused('a stored birth column is incomplete', MISSING, 'birth column') from exc


# ----------------------------------------------------------------------------- the state

def _thickness_ratios(record, piece, phases):
    """Current over declared thickness of each sublayer of ``piece``: the phase volume over area, shared by the
    sublayers of one phase (uniform strain within a phase, declared). Exact transport keeps the declared ratio."""
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
        return self._heat[self._offsets[index]:self._offsets[index+1]].copy()

    def supplied(self):
        return {name: value for name, value in self._supplied}

    def closure(self):
        total = sum((Fraction(float(x)) for x in self._heat), Fraction(0))
        booked = self._initial+sum((value for _, value in self._supplied), Fraction(0))+self._rounding
        return dict(identity_exact=total == booked and abs(self._rounding) <= self._allowance,
                    stored_j=float(total), rounding_j=float(self._rounding), allowance_j=float(self._allowance))

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
            declared_step=None):
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
    pieces = tuple((p.face_id, p.cohort_id) for p in material.pieces())
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
    total = sum((Fraction(float(x)) for x in heat_array), Fraction(0))
    if total != initial+sum((v for _, v in supplied), Fraction(0))+rounding or abs(rounding) > allowance:
        raise TransportRefused('the exact heat accounts do not close on the stored pieces: nothing is issued',
                               UNRESOLVED, 'accounts')
    packed = (('cohorts', _sphere._pack([r.record() for r in records])),
              ('heat_offsets', _sphere._frozen(np.asarray(offsets, dtype=np.int64), np.int64)),
              ('heat_j', heat_array))
    network = sphere.network
    record = _sphere._canonical(dict(
        schema=SCHEMA, producer=PRODUCER, state_id=sphere.state_id, network_id=network.network_id,
        material_id=material.material_id, time_s=network.time_s, step=network.step, declared_step=declared_step,
        frame_id=network.sphere.frame_id,
        enthalpy_reference_k=reference, quantities=dict(heat_j='J, signed, per piece and sublayer, against '
                                                               'enthalpy_reference_k'),
        accounts=_accounts_record(initial, supplied, rounding, allowance),
        lateral_omission_error_k=(UNKNOWN_BOUND if lateral_error is None else
                                  _accounts_record(lateral_error, (), Fraction(0), Fraction(0))['initial']),
        counts=dict(cohorts=len(records), pieces=len(pieces), values=len(values)),
        arrays=[dict(name=name, dtype=array.dtype.str, shape=list(array.shape)) for name, array in packed]),
        'moving state record')
    return _state._issue(MovingState, state_id=sphere.state_id, network_id=network.network_id,
                         material_id=material.material_id, time_s=network.time_s, step=network.step,
                         declared_step=declared_step,
                         frame_id=network.sphere.frame_id, enthalpy_reference_k=reference, cohorts=records,
                         moving_id=_sphere._identity(record, packed), _pieces=pieces,
                         _offsets=packed[1][1], _heat=heat_array, _initial=initial, _supplied=supplied,
                         _rounding=rounding, _allowance=allowance, _lateral_error=lateral_error, _record=record,
                         _packed=packed)


def _check_columns(sphere, records):
    """Each piece's declared phases are the cohort record's, with the declared thickness (I03 tolerance)."""
    by_id = {r.cohort_id: r for r in records}
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


def declare_moving(sphere, records, *, enthalpy_reference_k):
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
        ratios = _thickness_ratios(record, piece, sphere.material.phases)
        for ratio, sublayer in zip(ratios, record.sublayers):
            if abs(ratio-1) > _sphere.RELATIVE_TOLERANCE:
                raise TransportRefused('piece (%r, %r) does not hold its declared %r thickness'
                                       % (piece.face_id, piece.cohort_id, sublayer.phase), INCOMPATIBLE,
                                       piece.cohort_id)
        _check_reference_mass(record, piece, ratios, sphere.material.phases, 0)
        heat.append([s.declared_heat_per_area(reference)*piece.area_m2 for s in record.sublayers])
    initial = sum((Fraction(float(x)) for column in heat for x in column), Fraction(0))
    return _issued(sphere, records, heat, initial, (), Fraction(0), Fraction(0), reference)


def _check_reference_mass(record, piece, ratios, phases, intervals):
    """sum(rho_ref t) A per phase must equal the piece's I03 mass within inventory_bound(intervals) relative: P1's own
    guard, its row arithmetic (rho (h0 ratio) A, then fsum) and bound (review basal-02 and RB-2, 4 October 2026). A
    record admitted at declaration (intervals 0) or a piece admitted at its birth step therefore passes P1 there;
    refused ``incompatible support`` otherwise."""
    from .integration_properties import inventory_bound
    bound = inventory_bound(intervals)
    masses = dict(zip(phases, piece.mass_kg))
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


def restore_moving(record, arrays, sphere):
    """Rebuild a stored moving state through its constructors; its identity must reproduce, and the stored moving
    arrays must be exactly the rebuilt ones, byte for byte, with no other moving array (restore_sphere's exclusive
    check): an edit is refused, never sliced away."""
    if type(sphere) is not _sphere.SphereState:
        raise TransportRefused('a moving state is restored only beside its I03 SphereState', STALE, 'state')
    try:
        schema = record.get('schema') if type(record) is dict else None
        if schema != SCHEMA:
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
        state = _issued(sphere, cohorts, heat, initial, supplied, rounding, allowance, record['enthalpy_reference_k'],
                        lateral_error, record['declared_step'])
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, LedgerError, TectonicsError) as exc:
        if isinstance(exc, TransportRefused):
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
    """
    lateral: str
    nodes: tuple = ()
    certificate: object = None
    substeps: int = 1

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
        if self.lateral == 'omit' and self.certificate is None:
            raise TransportRefused('omitting lateral conduction needs an MC-06 certificate', MISSING, 'certificate')
        if self.certificate is not None:
            object.__setattr__(self, 'certificate', _certificate_text(self.certificate))

    def declared_certificate(self):
        """A fresh copy of the captured certificate, or None."""
        return None if self.certificate is None else json.loads(self.certificate)

    def record(self):
        return dict(lateral=self.lateral, nodes=[[f, list(d)] for f, d in self.nodes],
                    certificate=self.declared_certificate(), substeps=self.substeps)


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
    """
    start_step: int
    end_step: int
    births: tuple = ()
    conduction: object = None
    increments: tuple = ()
    driving: object = None
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
        return out

    def record(self):
        return dict(self._declared(), advance_id=self.advance_id)

    @staticmethod
    def from_record(row):
        try:
            conduction = row['conduction']
            if conduction is not None:
                conduction = Conduction(conduction['lateral'], tuple((f, tuple(d)) for f, d in conduction['nodes']),
                                        conduction['certificate'], conduction['substeps'])
            advance = MovingAdvance(row['start_step'], row['end_step'],
                                    tuple((h, BirthColumn.from_record(c)) for h, c in row['births']), conduction,
                                    tuple((tuple(k), tuple(v)) for k, v in row['increments']), row.get('driving'))
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
            raise TransportRefused('the stored moving advance is incomplete', MISSING, 'advance') from exc
        if row.get('schema') != ADVANCE_SCHEMA or _json(advance.record()) != _json(dict(row)):
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


def _apply_rows(rows, old_ids, new_ids, columns, book, sinks, births=()):
    """Exact transfer of per-piece sublayer heat over one set of rows, exactly as I03 transfers its own accounts.

    ``columns`` maps (old face index, cohort) to exact sublayer values. A piece of a face that is no row's donor is
    carried whole to the face with the same ID (I03's identity rule); every other piece is divided among its face's
    rows by I03's share rule (_split), each donor debited once; a consumption row books its part to the trench's
    destinations. Returns {(new face index, cohort): exact values}; same-cohort parts add, as I03's do.
    """
    donors_of = {}
    for row, donor in enumerate(rows.donor):
        if donor >= 0:
            donors_of.setdefault(donor, []).append(row)
    new_index = {name: i for i, name in enumerate(new_ids)}
    out = {}

    def add(key, values):
        slot = out.setdefault(key, [Fraction(0)]*len(values))
        for i, value in enumerate(values):
            slot[i] += value
    for (face, cohort), values in columns.items():
        if face not in donors_of:
            name = old_ids[face]
            if name not in new_index:
                raise TransportRefused('face %r disappears without any overlap row' % name, UNRESOLVED, name)
            add((new_index[name], cohort), values)
            continue
        areas = [Fraction(rows.area_m2[row]) for row in donors_of[face]]
        total, largest = sum(areas, Fraction(0)), _transfer._largest(areas)
        parts = [_transfer._split(value, areas, total, largest) for value in values]
        for k, row in enumerate(donors_of[face]):
            moved = [column[k] for column in parts]
            if rows.receiver[row] >= 0:
                add((rows.receiver[row], cohort), moved)
            else:
                party = rows.parties[rows.party[row]]
                _consumed(party[len('trench|'):], moved, book, sinks)
    for key, values in births:
        add(key, values)
    return out


def _consumed(boundary_id, values, book, sinks):
    sink = sinks.get(boundary_id)
    if sink is None:
        raise TransportRefused('trench %r consumes material but declares no destination' % boundary_id, MISSING,
                               boundary_id)
    amount = sum(values, Fraction(0))
    for destination, fraction, _ in sink.destinations:
        book(destination, -amount*Fraction(fraction))


def _born(step, columns_by_history, reference, book, sinks):
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
        _check_birth(column, supply)
        per_area = [Fraction(s.declared_heat_per_area(reference)) for s in column.sublayers]
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


def _check_birth(column, supply):
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
        h = math.fsum(s.thickness_m for s in column.sublayers if s.phase == phase)
        m = math.fsum(s.reference_density_kg_m3*s.thickness_m for s in column.sublayers if s.phase == phase)
        if (abs(h-thickness[phase]) > _sphere.RELATIVE_TOLERANCE*thickness[phase]
                or abs(m-mass[phase]) > inventory_bound(0)*mass[phase]):
            raise TransportRefused("the birth column of %r does not reproduce its supply's %r thickness and mass"
                                   % (supply.history_id, phase), INCOMPATIBLE, 'births')


def _transported(parent, sphere, step, advance, budget):
    """(cohort records, exact heat per endpoint (face, cohort), supplied bookings) after the step's rows, births,
    events and history splits. Nothing is averaged: rows divide each sublayer exactly as I03 divides its accounts."""
    motion = step.motion
    if motion.regional_returns:
        raise TransportRefused('a regional return moves material without rows: per-piece I05 content cannot follow '
                               'it (an I07 requirement)', UNSUPPORTED, 'regional_returns')
    supplied = dict(parent._supplied)

    def book(name, amount):
        supplied[name] = supplied.get(name, Fraction(0))+amount
    network = sphere.network
    face_index = {name: i for i, name in enumerate(network.face_ids)}
    columns = {(face_index[face], cohort): [Fraction(float(x)) for x in parent.heat_j(i)]
               for i, (face, cohort) in enumerate(parent.pieces)}
    records = {r.cohort_id: r for r in parent.cohorts}
    sinks = {s.boundary_id: s for s in motion.sinks}
    born, new_records = _born(step, dict(advance.births), parent.enthalpy_reference_k, book, sinks)
    records.update(new_records)
    moved_ids = _moved_face_ids(sphere, step, budget)
    moved = _apply_rows(step.map._motion, network.face_ids, moved_ids, columns, book, sinks, born)
    endpoint_ids = step.state.network.face_ids
    if step.map._mesh is not None:
        moved = _apply_rows(step.map._mesh, moved_ids, endpoint_ids, moved, book, sinks)
    result = {(endpoint_ids[target], cohort): values for (target, cohort), values in moved.items()}
    # History splits relabel named endpoint pieces; a sub-cohort's record copies its parent's, never averaged.
    for split in motion.history_splits:
        for history, faces in split.groups:
            child = _splits.sub_cohort_id(split.cohort_id, motion.end_step, history)
            records[child] = records[split.cohort_id].renamed(child)
            for face in faces:
                result[(face, child)] = result.pop((face, split.cohort_id))
    return records, result, supplied, set(new_records)


def _rounded(result, pieces):
    """Endpoint heat in I03 piece order, each value rounded once; the difference enters the exact rounding account
    within half a unit in the last place of each value it changes."""
    heat, rounding, allowance = [], Fraction(0), Fraction(0)
    for key in pieces:
        if key not in result:
            raise TransportRefused('endpoint piece (%r, %r) receives no heat' % key, UNRESOLVED, key[0])
        column = []
        for value in result.pop(key):
            stored = float(value)
            difference = Fraction(stored)-value
            if difference:
                rounding += difference
                allowance += Fraction(math.ulp(stored))/2
            column.append(stored)
        heat.append(column)
    if result:
        raise TransportRefused('heat arrived in a piece the I03 step does not hold: %r' % (next(iter(result)),),
                               UNRESOLVED, 'pieces')
    return heat, rounding, allowance


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
    records, result, supplied, born = _transported(parent, sphere, step, advance, budget)
    endpoint = step.state
    pieces = tuple((p.face_id, p.cohort_id) for p in endpoint.material.pieces())
    heat, rounding, allowance = _rounded(result, pieces)
    rounding += parent._rounding
    allowance += parent._allowance
    for cohort in endpoint.material.cohorts:
        if cohort.cohort_id not in records:
            raise TransportRefused('cohort %r of the endpoint has no record' % cohort.cohort_id, MISSING,
                                   cohort.cohort_id)
    for piece in endpoint.material.pieces():            # a born piece passes P1's guard at its birth step (RB-2)
        if piece.cohort_id in born:
            record = records[piece.cohort_id]
            _check_reference_mass(record, piece, _thickness_ratios(record, piece, endpoint.material.phases),
                                  endpoint.material.phases, endpoint.network.step-parent.declared_step)
    summary = dict(advance_id=advance.advance_id, map_id=step.map.map_id, parent_state_id=step.parent_state_id,
                   state_id=endpoint.state_id, transport='exact over the step rows',
                   conduction='none declared: advection only over this interval', increments=None)
    lateral_error = parent._lateral_error
    if advance.conduction is None:                     # no conduction: off the column-only trajectory, so UNKNOWN
        lateral_error = None
    else:
        from . import integration_thermal as _thermal
        before = sum((Fraction(x) for column in heat for x in column), Fraction(0))
        heat, report = _thermal.conducted(endpoint, records, heat, parent.enthalpy_reference_k, sphere, step,
                                          advance.conduction, budget, carried=lateral_error)
        after = sum((Fraction(x) for column in heat for x in column), Fraction(0))
        supplied[CONDUCTION_PARTY] = supplied.get(CONDUCTION_PARTY, Fraction(0))+(after-before)
        summary['conduction'] = report
        if report['certificate'] is not None:          # carried as the least binary64 value not below the bound
            lateral_error = Fraction(_thermal._upper_float(Fraction(report['certificate']['error_bound_exact_k'])))
    if advance.increments:
        records, applied = _incremented(records, pieces, advance.increments)
        summary['increments'] = applied
    state = _issued(endpoint, tuple(records[c.cohort_id] for c in endpoint.material.cohorts), heat, parent._initial,
                    tuple(supplied.items()), rounding, allowance, parent.enthalpy_reference_k, lateral_error,
                    parent.declared_step)
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
        parent = parent_record if parent_record.get('schema') == SCHEMA else parent_record['state']
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
    return record if record.get('schema') == SCHEMA else record['state']


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
