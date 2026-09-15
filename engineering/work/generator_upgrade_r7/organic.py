"""Finite-exposure natural organic-carbon pools, not universal RothC or peat.

All stocks/inputs are carbon kg per horizontal square metre. No implicit soil
temperature, litter, redox, calendar, density, nitrogen or horizon is generated.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction as F
import math

import numpy as np
from scipy.linalg import expm

STATUSES = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST', 'UNKNOWN', 'INCOMPLETE', 'CONFLICT'}
KNOWN = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'}
REGIMES = {'AERATED_MINERAL', 'WATERLOGGED_MINERAL', 'ORGANIC_DOMINATED'}
REDOX = {'OXIC', 'ANOXIC'}
MAX_BITS = 8192


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name+' needs bounded explicit text')
    return value


def _status(value):
    if type(value) is not str or value not in STATUSES:
        raise ValueError('explicit source status required')


def _number(value, name, *, positive=False, optional=False):
    if value is None and optional:
        return None
    if type(value) not in (int, float, F):
        raise ValueError(name+' needs an explicit finite quantity')
    if type(value) is float and not math.isfinite(value):
        raise ValueError(name+' must be finite')
    value = F(value)
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS:
        raise ValueError(name+' exceeds bounded exact representation')
    if value < 0 or (positive and value == 0):
        raise ValueError(name+' outside physical range')
    return value


def _float(value, name, *, positive=False, optional=False):
    exact = _number(value, name, positive=positive, optional=optional)
    if exact is None:
        return None
    try:
        result = float(exact)
    except OverflowError as error:
        raise ValueError(name+' not representable in numerical solver') from error
    if not math.isfinite(result) or (exact != 0 and result == 0):
        raise ValueError(name+' not representable in numerical solver')
    return result


@dataclass(frozen=True)
class OrganicState:
    layer_id: str
    support_id: str
    fast_carbon_kg_m2: F
    slow_carbon_kg_m2: F
    elapsed_seconds: F
    evidence: str
    source_status: str

    def __post_init__(self):
        for key in ('layer_id', 'support_id', 'evidence'):
            _text(getattr(self, key), key)
        for key in ('fast_carbon_kg_m2', 'slow_carbon_kg_m2', 'elapsed_seconds'):
            object.__setattr__(self, key, _number(getattr(self, key), key))
        _status(self.source_status)


def initial_state(layer_id, support_id, fast_carbon_kg_m2, slow_carbon_kg_m2, *, evidence, source_status):
    return OrganicState(layer_id, support_id, fast_carbon_kg_m2, slow_carbon_kg_m2, F(), evidence, source_status)


@dataclass(frozen=True)
class OrganicLaw:
    fast_rate_per_s: float | None
    slow_rate_per_s: float | None
    fast_to_slow_fraction: F | None
    carbon_fraction_dry_matter: F | None
    reference_temperature_k: float | None
    fast_activation_energy_j_mol: float | None
    slow_activation_energy_j_mol: float | None
    gas_constant_j_mol_k: float | None
    minimum_temperature_k: float
    maximum_temperature_k: float
    moisture_curve: tuple[tuple[float, float], ...]
    redox_factors: tuple[tuple[str, float, float], ...]
    regimes: tuple[str, ...]
    evidence: str
    source_status: str

    def __post_init__(self):
        for key in ('fast_rate_per_s', 'slow_rate_per_s', 'fast_activation_energy_j_mol', 'slow_activation_energy_j_mol'):
            object.__setattr__(self, key, _float(getattr(self, key), key, optional=True))
        for key in ('reference_temperature_k', 'gas_constant_j_mol_k'):
            object.__setattr__(self, key, _float(getattr(self, key), key, positive=True, optional=True))
        for key in ('minimum_temperature_k', 'maximum_temperature_k'):
            object.__setattr__(self, key, _float(getattr(self, key), key, positive=True))
        if self.minimum_temperature_k > self.maximum_temperature_k:
            raise ValueError('invalid temperature applicability interval')
        for key in ('fast_to_slow_fraction', 'carbon_fraction_dry_matter'):
            value = _number(getattr(self, key), key, positive=key=='carbon_fraction_dry_matter', optional=True)
            if value is not None and value > 1:
                raise ValueError(key+' must not exceed one')
            object.__setattr__(self, key, value)
        if type(self.moisture_curve) is not tuple or not 2 <= len(self.moisture_curve) <= 128:
            raise ValueError('explicit bounded WFPS response curve required')
        curve = []
        for row in self.moisture_curve:
            if type(row) is not tuple or len(row) != 2:
                raise ValueError('WFPS curve points must be pairs')
            curve.append(tuple(_float(v, 'WFPS response') for v in row))
        if curve[0][0] != 0 or curve[-1][0] != 1 or any(a[0] >= b[0] for a, b in zip(curve, curve[1:])):
            raise ValueError('WFPS knots must increase strictly from zero to one')
        object.__setattr__(self, 'moisture_curve', tuple(curve))
        if type(self.redox_factors) is not tuple or not 1 <= len(self.redox_factors) <= 2:
            raise ValueError('explicit oxic/anoxic process factors required')
        factors = []
        for row in self.redox_factors:
            if type(row) is not tuple or len(row) != 3 or row[0] not in REDOX:
                raise ValueError('redox row is (OXIC or ANOXIC, fast factor, slow factor)')
            factors.append((row[0], _float(row[1], 'fast redox factor'), _float(row[2], 'slow redox factor')))
        if len({row[0] for row in factors}) != len(factors):
            raise ValueError('duplicate redox interpretation')
        object.__setattr__(self, 'redox_factors', tuple(factors))
        if (type(self.regimes) is not tuple or not self.regimes or len(set(self.regimes)) != len(self.regimes)
                or any(value not in REGIMES for value in self.regimes)):
            raise ValueError('explicit admitted organic environments required')
        _text(self.evidence, 'law calibration/applicability evidence'); _status(self.source_status)


@dataclass(frozen=True)
class OrganicForcing:
    duration_seconds: F
    fast_litter_carbon_kg_m2_s: F | None
    slow_litter_carbon_kg_m2_s: F | None
    soil_temperature_k: float | None
    water_filled_pore_fraction: float | None
    redox: str
    regime: str
    climate_state_id: str
    water_state_id: str
    temperature_evidence: str
    litter_evidence: str
    evidence: str
    source_status: str

    def __post_init__(self):
        object.__setattr__(self, 'duration_seconds', _number(self.duration_seconds, 'duration_seconds'))
        for key in ('fast_litter_carbon_kg_m2_s', 'slow_litter_carbon_kg_m2_s'):
            object.__setattr__(self, key, _number(getattr(self, key), key, optional=True))
        object.__setattr__(self, 'soil_temperature_k', _float(self.soil_temperature_k, 'soil temperature', positive=True, optional=True))
        water = _float(self.water_filled_pore_fraction, 'WFPS', optional=True)
        if water is not None and water > 1:
            raise ValueError('WFPS must not exceed physical pore capacity')
        object.__setattr__(self, 'water_filled_pore_fraction', water)
        if type(self.redox) is not str or self.redox not in REDOX | {'UNKNOWN'}:
            raise ValueError('redox must be explicit, not inferred from saturation')
        if type(self.regime) is not str or self.regime not in REGIMES | {'UNKNOWN'}:
            raise ValueError('explicit environment regime required')
        for key in ('climate_state_id', 'water_state_id', 'temperature_evidence', 'litter_evidence', 'evidence'):
            _text(getattr(self, key), key)
        _status(self.source_status)


@dataclass(frozen=True)
class Numerics:
    probability_atol: float = 2e-11
    carbon_atol_kg_m2: float = 1e-12
    relative_tolerance: float = 1e-10
    max_rate_duration: float = 1e6
    max_segments: int = 4096

    def __post_init__(self):
        for key in ('probability_atol', 'carbon_atol_kg_m2', 'relative_tolerance', 'max_rate_duration'):
            object.__setattr__(self, key, _float(getattr(self, key), key, positive=True))
        if max(self.probability_atol, self.relative_tolerance) >= 1:
            raise ValueError('numerical relative tolerances must be below one')
        if type(self.max_segments) is not int or not 1 <= self.max_segments <= 4096:
            raise ValueError('bounded positive segment count required')


def _rate_pair(law, segment):
    moisture = float(np.interp(segment.water_filled_pore_fraction,
                              [p[0] for p in law.moisture_curve], [p[1] for p in law.moisture_curve]))
    redox = {row[0]: row[1:] for row in law.redox_factors}[segment.redox]
    result = []
    for base, energy, factor in zip((law.fast_rate_per_s, law.slow_rate_per_s),
                                   (law.fast_activation_energy_j_mol, law.slow_activation_energy_j_mol), redox):
        if base == 0 or moisture == 0 or factor == 0:
            result.append(0.)
            continue
        log_rate = (math.log(base)+math.log(moisture)+math.log(factor)
                    +energy/law.gas_constant_j_mol_k*(1/law.reference_temperature_k-1/segment.soil_temperature_k))
        rate = math.exp(log_rate)
        if not math.isfinite(rate) or rate == 0:
            raise ArithmeticError('unrepresentable effective decomposition rate')
        result.append(rate)
    return tuple(result), moisture


def _transitions(a, b, transfer, dt, controls):
    # Columns are source Fast/Slow/Gas. Gas is an absorbing carbon-origin pool.
    # Augmented upper-right block integrates exp(Q*s)/dt: continuous litter is
    # NOT placed at the start/end of an interval. The dimensionless block avoids
    # introducing raw long-duration seconds into the matrix exponential.
    x, y = a*dt, b*dt
    if not all(math.isfinite(v) for v in (x, y)) or max(x, y) > controls.max_rate_duration:
        raise ArithmeticError('rate-duration product exceeds declared numerical regime')
    if dt > 0 and ((a > 0 and x == 0) or (b > 0 and y == 0)):
        raise ArithmeticError('positive rate-duration product underflows')
    q = np.array([[-x, 0., 0.], [transfer*x, -y, 0.], [(1-transfer)*x, y, 0.]])
    block = np.zeros((6, 6)); block[:3, :3] = q; block[:3, 3:] = np.eye(3)
    exponential = expm(block)
    if exponential.shape != (6, 6) or not np.all(np.isfinite(exponential)):
        raise ArithmeticError('nonfinite/malformed organic transition')
    matrices, maximum_defect, maximum_change = [], 0., F()
    for raw in (exponential[:3, :2], exponential[:3, 3:5]):
        rows = []
        for column in raw.T:
            if np.any(column < 0):
                raise ArithmeticError('negative organic transition probability; no clipping')
            exact = tuple(F(float(v)) for v in column); total = sum(exact, F())
            defect = abs(total-1)
            if total <= 0 or defect > F(controls.probability_atol):
                raise ArithmeticError('organic transition fails conservation tolerance')
            normal = tuple(v/total for v in exact)
            maximum_defect = max(maximum_defect, float(defect))
            maximum_change = max(maximum_change, sum((abs(a-b) for a,b in zip(exact,normal)), F()))
            rows.append(normal)
        matrices.append(tuple(rows))
    return matrices[0], matrices[1], maximum_defect, maximum_change


def advance_layer(state, segments, law, *, numerics=None):
    """Constant-driver segments over an explicitly supplied local exposure.

    Failure/unknown outputs contain no partially modelled state or stock.
    Supplied coefficients admit their stated regime, not all Earth's/Diadem's
    soils. Spatial transport and density/geometry belong to the parent adapter.
    """
    controls = Numerics() if numerics is None else numerics
    if type(state) is not OrganicState or type(law) is not OrganicLaw or type(controls) is not Numerics:
        raise ValueError('typed organic state, law and numerical controls required')
    if type(segments) is not tuple or not 1 <= len(segments) <= controls.max_segments or any(type(v) is not OrganicForcing for v in segments):
        raise ValueError('bounded immutable forcing segment inventory required')
    result = {'schema':'diadem.organic-carbon-snapshot.r7', 'status':'UNKNOWN', 'state':None,
              'layer_id':state.layer_id, 'support_id':state.support_id,
              'source_status':'WORKING NON-CANON', 'final_organic_carbon_kg_m2':None,
              'final_organic_dry_mass_kg_m2':None, 'carbon':None, 'organic_dry_matter':None,
              'segments':[], 'law':asdict(law), 'numerics':asdict(controls),
              'nitrogen_release':{'value':None, 'mask':'NOT_MODELLED', 'reason':'carbon does not establish organic N stocks, stoichiometry or mineralisation fate'},
              'gas_speciation':{'co2_kg_m2':None, 'ch4_kg_m2':None, 'meaning':'exported carbon-origin mass only; no implied gas molecular mass'},
              'limitations':'two-pool prescribed-coefficient organic-C reference, not universal RothC, validated peat, microbial stoichiometry, solute transport or soil-temperature prediction'}
    required = ('fast_rate_per_s', 'slow_rate_per_s', 'fast_to_slow_fraction', 'carbon_fraction_dry_matter',
                'reference_temperature_k', 'fast_activation_energy_j_mol', 'slow_activation_energy_j_mol', 'gas_constant_j_mol_k')
    if state.source_status not in KNOWN or law.source_status not in KNOWN or any(getattr(law, key) is None for key in required):
        result['reason'] = 'initial stock or process-law evidence unresolved'
        return result
    redox = {row[0] for row in law.redox_factors}
    for segment in segments:
        if (segment.source_status not in KNOWN or segment.redox == 'UNKNOWN' or segment.regime == 'UNKNOWN'
                or any(getattr(segment, key) is None for key in ('fast_litter_carbon_kg_m2_s', 'slow_litter_carbon_kg_m2_s', 'soil_temperature_k', 'water_filled_pore_fraction'))):
            result['reason'] = 'actual/labeled temperature, moisture, natural litter or redox evidence unresolved'
            return result
        if (segment.regime not in law.regimes or segment.redox not in redox
                or not law.minimum_temperature_k <= segment.soil_temperature_k <= law.maximum_temperature_k):
            result.update(status='OUTSIDE_REGIME', reason='forcing lies outside explicitly supplied law applicability')
            return result
    fast, slow = state.fast_carbon_kg_m2, state.slow_carbon_kg_m2
    initial = fast+slow; inputs = F(); export = F(); time = state.elapsed_seconds; rows = []
    try:
        for index, segment in enumerate(segments):
            dt = _float(segment.duration_seconds, 'numerical segment duration')
            rates, moisture = _rate_pair(law, segment)
            transfer = _float(law.fast_to_slow_fraction, 'numerical carbon-transfer fraction')
            old_matrix, input_matrix, defect, correction = _transitions(*rates, transfer, dt, controls)
            litter = (segment.fast_litter_carbon_kg_m2_s*segment.duration_seconds,
                      segment.slow_litter_carbon_kg_m2_s*segment.duration_seconds)
            available = fast+slow+sum(litter, F())
            correction_bound = available*correction
            if correction_bound > F(controls.carbon_atol_kg_m2)+F(controls.relative_tolerance)*available:
                raise ArithmeticError('roundoff reconciliation exceeds carbon allowance')
            new = [F(), F(), F()]
            for stocks, matrix in (((fast, slow), old_matrix), (litter, input_matrix)):
                for stock, column in zip(stocks, matrix):
                    for destination in range(3):
                        new[destination] += stock*column[destination]
            if available != sum(new, F()):
                raise ArithmeticError('exact represented organic carbon does not close')
            for value in new:
                _number(value, 'updated organic stock')
            row = {'segment_index':index, 'start_seconds':time, 'duration_seconds':segment.duration_seconds,
                   'initial_carbon_kg_m2':fast+slow, 'input_carbon_kg_m2':sum(litter,F()),
                   'final_carbon_kg_m2':new[0]+new[1], 'exported_atmospheric_carbon_kg_m2':new[2],
                   'residual_kg_m2':F(), 'fast_rate_per_s':rates[0], 'slow_rate_per_s':rates[1],
                   'moisture_multiplier':moisture, 'forcing':asdict(segment),
                   'transition_column_sum_defect':defect, 'roundoff_reconciliation_bound_kg_m2':correction_bound}
            rows.append(row); fast, slow = new[:2]; export += new[2]; inputs += sum(litter,F()); time += segment.duration_seconds
        final = fast+slow
        residual = initial+inputs-final-export
        if residual != 0:
            raise ArithmeticError('whole exposure carbon accounting failed')
        final_state = OrganicState(state.layer_id, state.support_id, fast, slow, time,
                                   state.evidence, 'WORKING NON-CANON')
        carbon = {'initial_kg_m2':initial, 'input_kg_m2':inputs, 'final_kg_m2':final,
                  'exported_atmospheric_carbon_kg_m2':export, 'residual_kg_m2':residual}
        dry = {'initial_kg_m2':initial/law.carbon_fraction_dry_matter,
               'input_kg_m2':inputs/law.carbon_fraction_dry_matter,
               'final_kg_m2':final/law.carbon_fraction_dry_matter,
               'decomposed_dry_matter_origin_kg_m2':export/law.carbon_fraction_dry_matter,
               'residual_kg_m2':F(), 'carbon_fraction_dry_matter':law.carbon_fraction_dry_matter,
               'meaning':'dry-matter-origin accounting; noncarbon fate unresolved, not total atmospheric gas mass'}
        result.update(status='MODELLED', state=final_state, final_organic_carbon_kg_m2=final,
                      final_organic_dry_mass_kg_m2=dry['final_kg_m2'], carbon=carbon,
                      organic_dry_matter=dry, segments=rows,
                      reason='finite declared local exposure; no inferred history or horizon classification')
        return result
    except (ArithmeticError, ValueError, OverflowError, np.linalg.LinAlgError) as error:
        result.update(status='NUMERICAL_FAILURE', reason=str(error))
        return result


def state_to_record(state):
    if type(state) is not OrganicState:
        raise ValueError('OrganicState required')
    values = asdict(state)
    for key in ('fast_carbon_kg_m2', 'slow_carbon_kg_m2', 'elapsed_seconds'):
        value = values[key]; values[key] = [value.numerator, value.denominator]
    return {'schema':'diadem.organic-pool-state.r7', **values}


def state_from_record(record):
    names = set(OrganicState.__dataclass_fields__)
    if type(record) is not dict or set(record) != names | {'schema'} or record['schema'] != 'diadem.organic-pool-state.r7':
        raise ValueError('exact organic state fields/schema required')
    values = dict(record); del values['schema']
    for key in ('fast_carbon_kg_m2', 'slow_carbon_kg_m2', 'elapsed_seconds'):
        pair = values[key]
        if type(pair) is not list or len(pair) != 2 or any(type(v) is not int for v in pair) or pair[1] <= 0:
            raise ValueError('exact numerator/positive denominator required')
        values[key] = F(*pair)
    return OrganicState(**values)
