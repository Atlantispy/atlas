"""Pure bounded material transfers, not a calibrated terrain/karst/peat model.

All masses are dry constituent-origin masses. Rock-derived dissolved kg do not
include externally supplied reaction water/CO2. Carrier water m3 are conserved
under an explicitly dilute, constant-volume approximation. No implicit defaults,
file I/O, global climate lookup, routing, collapse or structural-safety claims.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import math

MAX_BATCH_CELLS = 16384
MASS_ATOL_KG = 1e-12
VOLUME_ATOL_M3 = 1e-15
BUDGET_RTOL = 5e-13
STATUS = "BOUNDED_REDUCED_LAWS_NOT_PHYSICAL_ACCEPTANCE"


class MaterialError(ValueError):
    """Invalid inputs, unsupported regime or unrepresentable numerical result."""


def _number(value, name, *, positive=False, fraction=False):
    if type(value) not in (int, float):
        raise MaterialError(name + " must be a real number, not Boolean")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise MaterialError(name + " is not representable in binary64") from exc
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise MaterialError(name + " must be finite and " + ("positive" if positive else "nonnegative"))
    if fraction and value > 1:
        raise MaterialError(name + " must be in [0,1]")
    return value


def _text(value, name):
    if type(value) is not str or not value.strip():
        raise MaterialError(name + " requires an explicit nonblank evidence/regime identifier")


def _finite(**values):
    for name, value in values.items():
        if not math.isfinite(value):
            raise MaterialError("nonfinite derived " + name)


def _positive_result(value, name):
    _finite(**{name: value})
    if value <= 0:
        raise MaterialError("positive derived " + name + " underflowed")
    return value


def _budget(values, atol):
    try:
        residual = math.fsum(values)
    except (OverflowError, ValueError) as exc:
        raise MaterialError("unrepresentable material budget") from exc
    _finite(residual=residual)
    if abs(residual) > atol + BUDGET_RTOL * max(abs(v) for v in values):
        raise MaterialError("material budget failed: " + repr(residual))
    return residual


def _normalise(instance, positive=(), fractions=(), text=("evidence_id",)):
    for field in fields(instance):
        value = getattr(instance, field.name)
        if field.name in text:
            _text(value, field.name)
        else:
            object.__setattr__(instance, field.name, _number(
                value, field.name, positive=field.name in positive,
                fraction=field.name in fractions))


@dataclass(frozen=True)
class SoilProductionParameters:
    bare_rate_m_per_year: float
    cover_scale_m: float
    rock_grain_density_kg_m3: float
    rock_porosity: float
    regolith_grain_density_kg_m3: float
    regolith_porosity: float
    mobile_grain_density_kg_m3: float
    mobile_porosity: float
    dissolved_rock_fraction: float
    mobile_fraction_of_retained_solids: float
    evidence_id: str

    def __post_init__(self):
        _normalise(self, positive=("cover_scale_m", "rock_grain_density_kg_m3",
                                  "regolith_grain_density_kg_m3", "mobile_grain_density_kg_m3"),
                   fractions=("rock_porosity", "regolith_porosity", "mobile_porosity",
                              "dissolved_rock_fraction", "mobile_fraction_of_retained_solids"))
        if max(self.rock_porosity, self.regolith_porosity, self.mobile_porosity) == 1:
            raise MaterialError("porosity must be less than one")
        for prefix in ("rock", "regolith", "mobile"):
            _positive_result(getattr(self, prefix + "_grain_density_kg_m3") *
                             (1 - getattr(self, prefix + "_porosity")), prefix + " bulk density")


@dataclass(frozen=True)
class SoilTransfer:
    rock_consumed_kg: float
    rock_remaining_kg: float
    regolith_produced_kg: float
    mobile_produced_kg: float
    dissolved_rock_produced_kg: float
    regolith_after_kg: float
    mobile_after_kg: float
    rock_solid_removed_m3: float
    rock_bulk_removed_m3: float
    regolith_solid_added_m3: float
    regolith_bulk_added_m3: float
    mobile_solid_added_m3: float
    mobile_bulk_added_m3: float
    bedrock_lowering_m: float
    surface_change_m: float
    initial_rate_m_per_year: float
    limited_by_available_rock: bool
    rock_mass_residual_kg: float


def soil_production_step(*, area_m2, rock_available_kg, regolith_kg,
                         mobile_kg, duration_years, parameters):
    """Exact closed-column P=P0 exp(-h/L), with fixed yields and porosities.

    h is total immobile+mobile bulk cover. Yield partition is a supplied
    rock-derived mass closure, NOT a mineral-reaction or climate prediction.
    No export/transport occurs within this operator. A finite rock inventory
    caps the integral; no unrelated bedrock process is implicitly activated.
    """
    if not isinstance(parameters, SoilProductionParameters):
        raise MaterialError("SoilProductionParameters required")
    p = parameters
    area = _number(area_m2, "area_m2", positive=True)
    rock = _number(rock_available_kg, "rock_available_kg")
    reg = _number(regolith_kg, "regolith_kg")
    mob = _number(mobile_kg, "mobile_kg")
    dt = _number(duration_years, "duration_years")
    rb = p.rock_grain_density_kg_m3 * (1 - p.rock_porosity)
    gb = p.regolith_grain_density_kg_m3 * (1 - p.regolith_porosity)
    mb = p.mobile_grain_density_kg_m3 * (1 - p.mobile_porosity)
    height = (reg / gb + mob / mb) / area
    solid_fraction = 1 - p.dissolved_rock_fraction
    mobile_fraction = solid_fraction * p.mobile_fraction_of_retained_solids
    reg_fraction = solid_fraction - mobile_fraction
    gamma = rb * (reg_fraction / gb + mobile_fraction / mb)
    exponent = height / p.cover_scale_m
    _finite(cover_height=height, cover_response=gamma, exponent=exponent)
    rate = p.bare_rate_m_per_year * math.exp(-exponent)
    lowering = 0.0
    if dt > 0 and rock > 0 and p.bare_rate_m_per_year > 0:
        _positive_result(rate, "soil production rate")
        unimpeded = _positive_result(rate * dt, "soil production interval")
        if gamma == 0:
            lowering = unimpeded
        else:
            scaled = _positive_result(gamma * unimpeded / p.cover_scale_m,
                                      "soil cover feedback")
            lowering = _positive_result((p.cover_scale_m / gamma) * math.log1p(scaled),
                                        "integrated bedrock lowering")
    demand = lowering * area * rb
    _finite(demand=demand)
    consumed = min(rock, demand)
    dissolved = consumed * p.dissolved_rock_fraction
    retained = consumed - dissolved
    produced_mobile = retained * p.mobile_fraction_of_retained_solids
    produced_reg = retained - produced_mobile
    rock_bulk = consumed / rb
    reg_bulk, mob_bulk = produced_reg / gb, produced_mobile / mb
    remaining = rock - consumed
    residual = _budget((consumed, -dissolved, -produced_mobile, -produced_reg), MASS_ATOL_KG)
    _budget((rock, -remaining, -consumed), MASS_ATOL_KG)
    result = SoilTransfer(consumed, remaining, produced_reg, produced_mobile, dissolved,
                          reg + produced_reg, mob + produced_mobile,
                          consumed / p.rock_grain_density_kg_m3, rock_bulk,
                          produced_reg / p.regolith_grain_density_kg_m3, reg_bulk,
                          produced_mobile / p.mobile_grain_density_kg_m3, mob_bulk,
                          rock_bulk / area, (reg_bulk + mob_bulk - rock_bulk) / area,
                          rate, demand > rock, residual)
    _finite(**{f.name: getattr(result, f.name) for f in fields(result)
               if f.name != "limited_by_available_rock"})
    return result


@dataclass(frozen=True)
class DissolutionParameters:
    mineral: str
    transfer_coefficient_m_per_year: float
    equilibrium_rock_equivalent_kg_m3: float
    minimum_saturation: float
    maximum_saturation: float
    grain_density_kg_m3: float
    evidence_id: str

    def __post_init__(self):
        _normalise(self, positive=("equilibrium_rock_equivalent_kg_m3", "grain_density_kg_m3"),
                   fractions=("minimum_saturation", "maximum_saturation"),
                   text=("mineral", "evidence_id"))
        if self.mineral not in ("calcite_linear_region_2", "gypsum_linear_film"):
            raise MaterialError("unsupported mineral/regime; no generic karst law")
        lower = .36 if self.mineral == "calcite_linear_region_2" else 0.
        if not lower <= self.minimum_saturation < self.maximum_saturation <= .9:
            raise MaterialError("unsupported saturation band for this reduced linear law")


@dataclass(frozen=True)
class DissolutionTransfer:
    rock_consumed_kg: float
    rock_remaining_kg: float
    dissolved_rock_input_kg: float
    dissolved_rock_output_kg: float
    dissolved_rock_produced_kg: float
    rock_solid_removed_m3: float
    carrier_water_input_m3: float
    carrier_water_output_m3: float
    concentration_after_kg_m3: float
    limited_by_available_rock: bool
    rock_mass_residual_kg: float
    water_residual_m3: float


def dissolution_step(*, rock_available_kg, water_m3, dissolved_rock_input_kg,
                     reactive_area_m2, duration_years, parameters):
    """Integrate dC/dt=(alpha*Areact/Vwater)*(Ceq-C) for one water parcel.

    Constant effective coefficient/chemistry/area; no water creation/loss, no
    mineral precipitation. Saturation-band exit is an error, not a silent cap
    at an arbitrary endpoint. The caller must split the step/change the law.
    Contact area is not inferred from cell area or invented fractures.
    """
    if not isinstance(parameters, DissolutionParameters):
        raise MaterialError("DissolutionParameters required")
    p = parameters
    rock = _number(rock_available_kg, "rock_available_kg")
    water = _number(water_m3, "water_m3")
    incoming = _number(dissolved_rock_input_kg, "dissolved_rock_input_kg")
    area = _number(reactive_area_m2, "reactive_area_m2")
    dt = _number(duration_years, "duration_years")
    if water == 0:
        if incoming != 0:
            raise MaterialError("dissolved material without carrier water")
        return DissolutionTransfer(0., rock, 0., 0., 0., 0., 0., 0., 0., False, 0., 0.)
    initial = incoming / water
    saturation = initial / p.equilibrium_rock_equivalent_kg_m3
    _finite(initial_concentration=initial, saturation=saturation)
    if not p.minimum_saturation <= saturation <= p.maximum_saturation:
        raise MaterialError("initial concentration outside supported saturation band")
    potential = 0.
    if rock and area and dt and p.transfer_coefficient_m_per_year:
        exponent = _positive_result(p.transfer_coefficient_m_per_year * area * dt / water,
                                    "dissolution exposure")
        deficit = p.equilibrium_rock_equivalent_kg_m3 - initial
        potential = _positive_result(water * deficit * -math.expm1(-exponent),
                                     "dissolution transfer")
    consumed = min(rock, potential)
    outgoing = incoming + consumed
    final = outgoing / water
    _finite(outgoing=outgoing, final_concentration=final)
    if final / p.equilibrium_rock_equivalent_kg_m3 > p.maximum_saturation:
        raise MaterialError("interval crosses supported saturation band; reduce step or change law")
    remaining = rock - consumed
    residual = _budget((rock, incoming, -remaining, -outgoing), MASS_ATOL_KG)
    result = DissolutionTransfer(consumed, remaining, incoming, outgoing, consumed,
                                 consumed / p.grain_density_kg_m3, water, water, final,
                                 potential > rock, residual, 0.)
    _finite(**{f.name: getattr(result, f.name) for f in fields(result)
               if f.name != "limited_by_available_rock"})
    return result


@dataclass(frozen=True)
class OrganicParameters:
    input_dry_organic_kg_m2_per_year: float
    input_dry_mineral_kg_m2_per_year: float
    decay_per_year: float
    organic_grain_density_kg_m3: float
    mineral_grain_density_kg_m3: float
    evidence_id: str

    def __post_init__(self):
        _normalise(self, positive=("organic_grain_density_kg_m3", "mineral_grain_density_kg_m3"))


@dataclass(frozen=True)
class OrganicTransfer:
    organic_after_kg: float
    mineral_after_kg: float
    organic_input_kg: float
    mineral_input_kg: float
    decomposed_organic_origin_kg: float
    solid_volume_before_m3: float
    solid_volume_after_m3: float
    bulk_volume_before_m3: float
    bulk_volume_after_m3: float
    thickness_change_m: float
    pore_water_before_m3: float
    pore_water_after_m3: float
    external_water_supplied_m3: float
    water_output_m3: float
    organic_mass_residual_kg: float
    mineral_mass_residual_kg: float
    water_residual_m3: float


def organic_step(*, area_m2, organic_kg, mineral_kg, void_ratio,
                 external_water_m3, duration_years, parameters):
    """Exact dM/dt=I-kM at fixed void ratio, followed by saturation bookkeeping.

    I is explicitly supplied dry matter entering the represented peat pool,
    not inferred NPP. Decayed organic-origin kg are an un-speciated export,
    NOT CO2/CH4 chemical kg or measured carbon. Initial pore water is the
    fully saturated inventory e*Vsolid. Insufficient supplied water fails.
    Compaction is a separate operator, avoiding double-counted loss of solids.
    """
    if not isinstance(parameters, OrganicParameters):
        raise MaterialError("OrganicParameters required")
    p = parameters
    area = _number(area_m2, "area_m2", positive=True)
    organic = _number(organic_kg, "organic_kg")
    mineral = _number(mineral_kg, "mineral_kg")
    e = _number(void_ratio, "void_ratio")
    water_in = _number(external_water_m3, "external_water_m3")
    dt = _number(duration_years, "duration_years")
    organic_in = p.input_dry_organic_kg_m2_per_year * area * dt
    mineral_in = p.input_dry_mineral_kg_m2_per_year * area * dt
    x = p.decay_per_year * dt
    _finite(organic_input=organic_in, mineral_input=mineral_in, decay_interval=x)
    if dt > 0:
        if p.input_dry_organic_kg_m2_per_year > 0:
            _positive_result(organic_in, "organic interval input")
        if p.input_dry_mineral_kg_m2_per_year > 0:
            _positive_result(mineral_in, "mineral interval input")
    if x == 0:
        if p.decay_per_year > 0 and dt > 0:
            raise MaterialError("decay interval underflow")
        loss, organic_after = 0., organic + organic_in
    else:
        lost_fraction = -math.expm1(-x)
        survival_of_input = lost_fraction / x
        # Stable 1-(1-exp(-x))/x avoids cancellation for short intervals.
        input_loss_fraction = (x * (.5 + x * (-1/6 + x * (1/24 + x * (-1/120 + x/720))))) if x < 1e-4 else 1 - survival_of_input
        loss = organic * lost_fraction + organic_in * input_loss_fraction
        organic_after = organic * math.exp(-x) + organic_in * survival_of_input
    mineral_after = mineral + mineral_in
    before_solid = organic / p.organic_grain_density_kg_m3 + mineral / p.mineral_grain_density_kg_m3
    after_solid = organic_after / p.organic_grain_density_kg_m3 + mineral_after / p.mineral_grain_density_kg_m3
    water_before, water_after = e * before_solid, e * after_solid
    _finite(solid_volume_before=before_solid, solid_volume_after=after_solid,
            pore_water_before=water_before, pore_water_after=water_after)
    water_out = math.fsum((water_before, water_in, -water_after))
    if water_out < 0:
        raise MaterialError("insufficient external water to keep organic column saturated")
    organic_residual = _budget((organic, organic_in, -organic_after, -loss), MASS_ATOL_KG)
    mineral_residual = _budget((mineral, mineral_in, -mineral_after), MASS_ATOL_KG)
    water_residual = _budget((water_before, water_in, -water_after, -water_out), VOLUME_ATOL_M3)
    result = OrganicTransfer(organic_after, mineral_after, organic_in, mineral_in, loss,
                             before_solid, after_solid, (1+e)*before_solid, (1+e)*after_solid,
                             (1+e)*(after_solid-before_solid)/area,
                             water_before, water_after, water_in, water_out,
                             organic_residual, mineral_residual, water_residual)
    _finite(**{f.name: getattr(result, f.name) for f in fields(result)})
    return result


@dataclass(frozen=True)
class CompactionParameters:
    compression_index: float
    minimum_effective_stress_pa: float
    maximum_effective_stress_pa: float
    evidence_id: str

    def __post_init__(self):
        _normalise(self, positive=("minimum_effective_stress_pa", "maximum_effective_stress_pa"))
        if self.maximum_effective_stress_pa < self.minimum_effective_stress_pa:
            raise MaterialError("inverted compaction calibration interval")


@dataclass(frozen=True)
class CompactionTransfer:
    void_ratio_after: float
    solid_volume_m3: float
    bulk_volume_before_m3: float
    bulk_volume_after_m3: float
    settlement_m: float
    pore_water_before_m3: float
    pore_water_after_m3: float
    expelled_water_m3: float
    water_residual_m3: float


def compact_saturated_column(*, area_m2, solid_volume_m3, void_ratio,
                             effective_stress_before_pa, effective_stress_after_pa,
                             parameters):
    """Normally consolidated EOP log10 stress/void-ratio endpoint, no dynamics.

    Caller supplies effective (not total) stress and laboratory-supported Cc
    range. Both endpoints must be on the same virgin-compression branch.
    No unloading, overconsolidation, creep, solid compression or safety model.
    Saturated, incompressible solids/carrier water: volume loss expels water.
    """
    if not isinstance(parameters, CompactionParameters):
        raise MaterialError("CompactionParameters required")
    p = parameters
    area = _number(area_m2, "area_m2", positive=True)
    solid = _number(solid_volume_m3, "solid_volume_m3")
    e = _number(void_ratio, "void_ratio")
    before = _number(effective_stress_before_pa, "effective_stress_before_pa", positive=True)
    after = _number(effective_stress_after_pa, "effective_stress_after_pa", positive=True)
    if not p.minimum_effective_stress_pa <= before <= after <= p.maximum_effective_stress_pa:
        raise MaterialError("outside calibrated monotonic virgin-compaction stress interval")
    # log1p preserves close stress endpoints; fallback avoids ratio overflow.
    relative_increment = (after - before) / before
    log_ratio = (math.log1p(relative_increment) / math.log(10)
                 if math.isfinite(relative_increment) else math.log10(after) - math.log10(before))
    delta = p.compression_index * log_ratio
    _finite(void_ratio_change=delta)
    e_after = e - delta
    if e_after < 0:
        raise MaterialError("compaction would give negative void ratio; no clipping")
    if delta > 0 and e_after == e:
        raise MaterialError("compaction endpoint change is below binary64 resolution")
    initial_water, final_water = solid * e, solid * e_after
    expelled = solid * delta
    residual = _budget((initial_water, -final_water, -expelled), VOLUME_ATOL_M3)
    result = CompactionTransfer(e_after, solid, solid*(1+e), solid*(1+e_after),
                                expelled/area, initial_water, final_water, expelled, residual)
    _finite(**{f.name: getattr(result, f.name) for f in fields(result)})
    return result


def _batch(cells, parameters, function, parameter_type):
    if not isinstance(parameters, parameter_type):
        raise MaterialError(parameter_type.__name__ + " required even for empty batch")
    if type(cells) not in (list, tuple) or len(cells) > MAX_BATCH_CELLS:
        raise MaterialError("batch must be a list/tuple of at most16384 cells")
    if any(type(cell) is not dict or "parameters" in cell for cell in cells):
        raise MaterialError("each batch cell must be a scalar argument dictionary")
    try:
        return tuple(function(parameters=parameters, **cell) for cell in cells)
    except TypeError as exc:
        raise MaterialError("invalid batch cell schema") from exc


def soil_production_batch(cells, parameters):
    return _batch(cells, parameters, soil_production_step, SoilProductionParameters)


def dissolution_batch(cells, parameters):
    return _batch(cells, parameters, dissolution_step, DissolutionParameters)


def organic_batch(cells, parameters):
    return _batch(cells, parameters, organic_step, OrganicParameters)


def compaction_batch(cells, parameters):
    return _batch(cells, parameters, compact_saturated_column, CompactionParameters)
