"""Finite nutrient release/retention and an explicit natural-reference index.

Every stock is elemental kg per horizontal square metre. This is an open,
well-mixed reference assay, not plant uptake, a full reactive chemistry solver,
or a universal measure of ecological productivity. No fertiliser/crop inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from fractions import Fraction
import math

import numpy as np
from scipy.linalg import expm


NUTRIENTS = ('N', 'P', 'K')
MAX_SEGMENTS = 4096


def text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + ' requires bounded evidence/identity')
    return value


def number(value, name, *, minimum=0., maximum=1e100, positive=False):
    if type(value) not in (int, float):
        raise ValueError(name + ' requires a finite number, not bool/UNKNOWN')
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(name + ' exceeds finite range') from exc
    if not math.isfinite(value):
        raise ValueError(name + ' requires a finite number')
    if not minimum <= value <= maximum or (positive and value <= 0):
        raise ValueError(name + ' outside supported physical/numerical range')
    return value


def checked_values(instance, names, **bounds):
    for name in names:
        object.__setattr__(instance, name, number(getattr(instance, name), name, **bounds))


@dataclass(frozen=True)
class Chemistry:
    chemistry_id: str
    ph_water: float
    electrical_conductivity_ds_m: float
    cec_method: str
    evidence: str

    def __post_init__(self):
        for key in ('chemistry_id', 'cec_method', 'evidence'):
            text(getattr(self, key), key)
        checked_values(self, ('ph_water',), maximum=14.)
        checked_values(self, ('electrical_conductivity_ds_m',), maximum=1000.)


@dataclass(frozen=True)
class NutrientPool:
    nutrient: str
    reserve_kg_m2: float
    labile_kg_m2: float
    evidence: str

    def __post_init__(self):
        if self.nutrient not in NUTRIENTS:
            raise ValueError('explicit elemental N/P/K pool required')
        text(self.evidence, 'pool evidence')
        checked_values(self, ('reserve_kg_m2', 'labile_kg_m2'), maximum=1e8)


@dataclass(frozen=True)
class NutrientLaw:
    nutrient: str
    release_per_s: float
    kd_m3_kg: float
    available_fraction: float
    reference_temperature_k: float
    activation_energy_j_mol: float
    gas_constant_j_mol_k: float
    chemistry_id: str
    species: str
    evidence: str

    def __post_init__(self):
        if self.nutrient not in NUTRIENTS:
            raise ValueError('explicit elemental N/P/K law required')
        for key in ('chemistry_id', 'species', 'evidence'):
            text(getattr(self, key), key)
        checked_values(self, ('release_per_s',), maximum=1.)
        checked_values(self, ('kd_m3_kg',), maximum=1e6)
        checked_values(self, ('available_fraction',), maximum=1.)
        checked_values(self, ('reference_temperature_k',), minimum=200., maximum=350.)
        checked_values(self, ('activation_energy_j_mol',), maximum=200000.)
        checked_values(self, ('gas_constant_j_mol_k',), positive=True, maximum=100.)
        if self.species == 'NITRATE_N' and (self.nutrient != 'N' or self.kd_m3_kg != 0):
            raise ValueError('this reference nitrate case has no cation-exchange sorption')


@dataclass(frozen=True)
class WaterExposure:
    duration_s: float
    temperature_k: float
    wetness: float
    water_storage_m: float
    downward_m_s: float
    upward_m_s: float
    upward_concentration_kg_m3: float | None
    evidence: str

    def __post_init__(self):
        checked_values(self, ('duration_s',), maximum=1e13)
        checked_values(self, ('temperature_k',), minimum=200., maximum=350.)
        checked_values(self, ('wetness',), maximum=1.)
        checked_values(self, ('water_storage_m',), maximum=1e4)
        checked_values(self, ('downward_m_s', 'upward_m_s'), maximum=1.)
        if self.upward_concentration_kg_m3 is not None:
            checked_values(self, ('upward_concentration_kg_m3',), maximum=1e5)
        if self.upward_m_s and self.upward_concentration_kg_m3 is None:
            raise ValueError('upward water requires its nutrient concentration; UNKNOWN is not zero')
        if self.water_storage_m == 0 and (self.downward_m_s or self.upward_m_s):
            raise ValueError('dry well-mixed assay cannot carry water flow')
        text(self.evidence, 'exposure evidence')


def advance_nutrient(pool, law, exposures, *, sorbent_mass_kg_m2, chemistry, support_id):
    """R'=-kR; L'=kR+q_up*c_up-q_down*L/(W+Kd*M).

    L includes dissolved plus reversibly sorbed nutrient at local equilibrium.
    Kd is constituent/matrix specific, not calculated from CEC. The supplied
    release rate is NET reserve-to-labile conversion, not gross SOC decay.
    A separate export state supplies an independently integrated mass ledger.
    """
    if type(pool) is not NutrientPool or type(law) is not NutrientLaw or type(chemistry) is not Chemistry:
        raise ValueError('typed nutrient, law and chemical context required')
    if pool.nutrient != law.nutrient or law.chemistry_id != chemistry.chemistry_id:
        raise ValueError('nutrient/chemical law binding differs')
    mass = number(sorbent_mass_kg_m2, 'sorbent mass', maximum=1e8)
    text(support_id, 'physical assay support identity')
    if type(exposures) is not tuple or not 1 <= len(exposures) <= MAX_SEGMENTS or any(type(x) is not WaterExposure for x in exposures):
        raise ValueError('bounded explicit exposure tuple required')
    r, l = pool.reserve_kg_m2, pool.labile_kg_m2
    initial = Fraction(r) + Fraction(l)
    imported = Fraction(); exported = Fraction(); rows = []
    for segment in exposures:
        exponent = law.activation_energy_j_mol / law.gas_constant_j_mol_k * (1 / law.reference_temperature_k - 1 / segment.temperature_k)
        modifier = math.exp(exponent) * segment.wetness
        rate = number(law.release_per_s * modifier, 'temperature/moisture-adjusted release', maximum=1e3)
        capacity = number(segment.water_storage_m + law.kd_m3_kg * mass, 'linear equilibrium capacity', maximum=1e15)
        flush = segment.downward_m_s / capacity if capacity else 0.
        incoming = segment.upward_m_s * (segment.upward_concentration_kg_m3 or 0.)
        dt = segment.duration_s
        if dt > 0 and segment.upward_m_s > 0 and (segment.upward_concentration_kg_m3 or 0.) > 0:
            if incoming == 0 or incoming * dt == 0:
                raise ValueError('positive external nutrient input underflows; not a zero-input assay')
        if max(rate, flush) * dt > 10000:
            raise ValueError('exposure exceeds supported matrix-exponential regime; split declared forcing')
        # Constant-input augmentation; all off-diagonal rates are nonnegative.
        matrix = np.array([[-rate, 0., 0., 0.], [rate, -flush, 0., incoming],
                           [0., flush, 0., 0.], [0., 0., 0., 0.]])
        new = expm(matrix * dt) @ np.array([r, l, 0., 1.])
        if not np.isfinite(new).all() or np.any(new < 0):
            raise ArithmeticError('nutrient propagation is nonfinite/negative; no clipping')
        nr, nl, loss, constant = map(float, new)
        added = number(incoming * dt, 'imported nutrient', maximum=1e15)
        residual = Fraction(r) + Fraction(l) + Fraction(added) - Fraction(nr) - Fraction(nl) - Fraction(loss)
        allowance = 1e-12 + 1e-10 * (r + l + added)
        if abs(float(residual)) > allowance or abs(constant - 1) > 1e-12:
            raise ArithmeticError('independent nutrient mass balance failed')
        rows.append({'duration_s': dt, 'release_rate_per_s': rate, 'leaching_rate_per_s': flush,
                     'imported_kg_m2': added, 'exported_kg_m2': loss,
                     'numerical_residual_kg_m2': str(residual), 'evidence': segment.evidence})
        r, l = nr, nl
        imported += Fraction(added); exported += Fraction(loss)
    last = exposures[-1]
    capacity = last.water_storage_m + law.kd_m3_kg * mass
    dissolved = l * last.water_storage_m / capacity if capacity else 0.
    sorbed = l - dissolved if capacity else 0.
    # A completely dry, nonsorbing assay has solid labile nutrient, not invented
    # dissolved concentration or reversible sorption.
    dry_labile = l if capacity == 0 else 0.
    residual = initial + imported - Fraction(r) - Fraction(l) - exported
    return {'schema': 'diadem.nutrient-reference.r7', 'nutrient': pool.nutrient,
            'reserve_kg_m2': r, 'labile_kg_m2': l, 'dissolved_kg_m2': dissolved,
            'reversibly_sorbed_kg_m2': sorbed, 'dry_labile_kg_m2': dry_labile,
            'available_retained_kg_m2': l * law.available_fraction,
            'initial_kg_m2': str(initial), 'imported_kg_m2': str(imported),
            'exported_kg_m2': str(exported), 'numerical_residual_kg_m2': str(residual),
            'chemistry': asdict(chemistry), 'pool_evidence': pool.evidence, 'law': asdict(law),
            'initial_pool': asdict(pool), 'sorbent_mass_kg_m2': mass,
            'support_id': support_id,
            'exposures': [asdict(x) for x in exposures],
            'segments': rows, 'source_status': 'WORKING NON-CANON',
            'scope': 'net reserve release and linear equilibrium labile partition; no plant uptake, full speciation, redox reaction or microbial immobilisation prediction'}


@dataclass(frozen=True)
class ExchangeComponent:
    component_id: str
    mass_kg_m2: float
    cec_cmolc_kg: float
    method: str
    evidence: str

    def __post_init__(self):
        for key in ('component_id', 'method', 'evidence'):
            text(getattr(self, key), key)
        checked_values(self, ('mass_kg_m2',), maximum=1e8)
        checked_values(self, ('cec_cmolc_kg',), maximum=1e5)


def exchange_capacity(components, *, dry_fine_earth_and_organic_mass_kg_m2, chemistry, support_id):
    """Mass-additive charge capacity in one explicitly shared assay method.

    Denominator includes fine mineral earth plus dry organic matter, not rock
    fragments. Organic-rich/organic-only profiles need no mineral denominator.
    Unlisted mass is NOT presumed to have zero charge: all mass must be listed.
    """
    if type(chemistry) is not Chemistry or type(components) is not tuple or not 1 <= len(components) <= 128:
        raise ValueError('typed bounded exchange components/context required')
    if any(type(x) is not ExchangeComponent for x in components) or len({x.component_id for x in components}) != len(components):
        raise ValueError('unique exchange components required')
    total = number(dry_fine_earth_and_organic_mass_kg_m2, 'dry assay mass', positive=True, maximum=1e8)
    text(support_id, 'physical assay support identity')
    summed = sum((Fraction(x.mass_kg_m2) for x in components), Fraction())
    if abs(float(summed - Fraction(total))) > 1e-12 * total:
        raise ValueError('exchange inventory must account for all dry assay mass')
    if any(x.method != chemistry.cec_method for x in components):
        raise ValueError('cannot mix potential/field CEC or different chemical methods')
    charge = sum((Fraction(x.mass_kg_m2) * Fraction(x.cec_cmolc_kg) for x in components), Fraction())
    cec = float(charge / summed)
    return {'cec_cmolc_kg': cec, 'exchange_capacity_cmolc_m2': float(charge),
            'support_id': support_id,
            'dry_assay_mass_kg_m2': float(summed), 'chemistry': asdict(chemistry),
            'components': [asdict(x) for x in components],
            'scope': 'mass-additive capacity at stated chemical method; not field speciation or nitrate retention'}


@dataclass(frozen=True)
class FertilityProtocol:
    protocol_id: str
    nitrogen_reference_kg_m2: float
    phosphorus_reference_kg_m2: float
    potassium_reference_kg_m2: float
    exchange_reference_cmolc_m2: float
    evidence: str

    def __post_init__(self):
        text(self.protocol_id, 'protocol identity'); text(self.evidence, 'natural reference rationale')
        checked_values(self, ('nitrogen_reference_kg_m2', 'phosphorus_reference_kg_m2',
                             'potassium_reference_kg_m2', 'exchange_reference_cmolc_m2'), positive=True, maximum=1e10)


def profile_fertility(nutrient_results, exchange_result, protocol, *, natural_reference_evidence):
    """F=min(N/(N+Nref), P/(P+Pref), K/(K+Kref), Q/(Q+Qref)).

    These declared reference scales set 0.5, not agronomic deficiency thresholds.
    No averaging away a limiting nutrient; no claim that all natural organisms
    share nutrient needs. UNKNOWN propagates to the index, never a false zero.
    """
    if type(protocol) is not FertilityProtocol or type(nutrient_results) is not dict or set(nutrient_results) != set(NUTRIENTS):
        raise ValueError('complete explicit N/P/K inventory and protocol required')
    text(natural_reference_evidence, 'unfertilised/unirrigated reference evidence')
    references = dict(zip(NUTRIENTS, (protocol.nitrogen_reference_kg_m2, protocol.phosphorus_reference_kg_m2, protocol.potassium_reference_kg_m2)))
    factors = {}; reasons = []
    common_chemistry = None; common_exposure = None; common_mass = None; common_support = None
    for nutrient, row in nutrient_results.items():
        if row is None:
            factors[nutrient] = None; reasons.append(nutrient + ' supply UNKNOWN'); continue
        if type(row) is not dict or row.get('schema') != 'diadem.nutrient-reference.r7' or row.get('nutrient') != nutrient:
            raise ValueError('computed matching nutrient reference required')
        support = [{k: v for k, v in x.items() if k not in ('evidence', 'upward_concentration_kg_m3')}
                   for x in row['exposures']]
        if common_chemistry is None:
            common_chemistry, common_exposure = row['chemistry'], support
            common_mass = number(row['sorbent_mass_kg_m2'], 'dry assay mass', maximum=1e8)
            common_support = text(row['support_id'], 'assay support')
        elif (row['chemistry'] != common_chemistry or support != common_exposure
              or row['support_id'] != common_support or row['sorbent_mass_kg_m2'] != common_mass):
            raise ValueError('nutrient chemical/physical exposure support differs')
        # Later boundary influx is natural, but is not INHERENT soil supply.
        if (Fraction(row['imported_kg_m2']) != 0 or any(x['duration_s'] > 0 and x['upward_m_s'] > 0
            and (x['upward_concentration_kg_m3'] or 0.) > 0 for x in row['exposures'])):
            raise ValueError('inherent fertility assay must exclude future external nutrient imports')
        value = number(row['available_retained_kg_m2'], nutrient + ' retained supply', maximum=1e15)
        factors[nutrient] = value / (value + references[nutrient])
    if exchange_result is None:
        factors['retention'] = None; reasons.append('exchange capacity UNKNOWN')
    else:
        if common_chemistry is not None and exchange_result['chemistry'] != common_chemistry:
            raise ValueError('exchange and nutrient chemical supports differ')
        if common_support is not None and (exchange_result['support_id'] != common_support or
                abs(exchange_result['dry_assay_mass_kg_m2'] - common_mass) > 1e-12 * common_mass):
            raise ValueError('exchange and nutrient dry assay mass/support differ')
        value = number(exchange_result['exchange_capacity_cmolc_m2'], 'charge capacity', maximum=1e15)
        factors['retention'] = value / (value + protocol.exchange_reference_cmolc_m2)
    index = None if reasons else min(factors.values())
    return {'schema': 'diadem.inherent-fertility.r7', 'index_0_1': index,
            'status': 'UNKNOWN' if reasons else 'MODELLED_NATURAL_REFERENCE', 'reasons': reasons,
            'factors': factors, 'nutrients': nutrient_results, 'exchange': exchange_result,
            'protocol': asdict(protocol), 'natural_reference_evidence': natural_reference_evidence,
            'source_status': 'WORKING NON-CANON',
            'uncertainty': 'one explicit joint case, not a calibrated confidence interval; compare coequal scenarios without selecting a median',
            'excluded': ['fertiliser', 'irrigation', 'crop yield', 'universal species suitability', 'inferred pH', 'inferred nutrient chemistry']}
