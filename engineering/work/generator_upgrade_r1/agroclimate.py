"""Explicit daily root-zone water balance and bounded seasonal yield response.

FAO56 equations 81--85 (single crop coefficient) and FAO33 seasonal Ky law.
This is a reduced, fixed-root, well-drained, non-saline scenario calculation,
not AquaCrop, daily weather generation or a universal crop productivity model.
Beginning-of-day depletion determines stress; water above field capacity drains
after that day's ET. Net irrigation is water reaching the root zone, not the
gross extraction from a shared irrigation pool. All coefficients are supplied.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


def number(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ValueError(name + " must be an explicit number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(name + " is unrepresentable") from exc
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        raise ValueError(name + " must be finite and " + ("positive" if positive else "nonnegative"))
    return result


def provenance(evidence, source_status):
    if type(evidence) is not str or not evidence.strip():
        raise ValueError("explicit physical parameter/forcing evidence is required")
    if source_status not in {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST", "UNKNOWN"}:
        raise ValueError("unsupported source status")


@dataclass(frozen=True)
class RootZone:
    field_capacity_m3_m3: float
    wilting_point_m3_m3: float
    rooting_depth_m: float
    depletion_fraction: float
    evidence: str
    source_status: str

    def __post_init__(self):
        provenance(self.evidence, self.source_status)
        if self.source_status == "UNKNOWN":
            raise ValueError("unknown soil properties cannot instantiate a known root zone")
        for key in ("field_capacity_m3_m3", "wilting_point_m3_m3", "rooting_depth_m", "depletion_fraction"):
            object.__setattr__(self, key, number(getattr(self, key), key, positive=key == "rooting_depth_m"))
        if not self.wilting_point_m3_m3 < self.field_capacity_m3_m3 <= 1:
            raise ValueError("require 0 <= wilting point < field capacity <= 1")
        if self.depletion_fraction >= 1:
            raise ValueError("require 0 <= depletion fraction < 1 for this stress law")
        number(1000 * (self.field_capacity_m3_m3-self.wilting_point_m3_m3) * self.rooting_depth_m,
               "total available water", positive=True)

    @property
    def available_water_mm(self):
        return 1000 * (self.field_capacity_m3_m3-self.wilting_point_m3_m3) * self.rooting_depth_m


@dataclass(frozen=True)
class DayForcing:
    precipitation_mm: float
    runoff_mm: float
    net_irrigation_mm: float
    capillary_rise_mm: float
    potential_crop_et_mm: float

    def __post_init__(self):
        for key in self.__dataclass_fields__:
            object.__setattr__(self, key, number(getattr(self, key), key))
        if self.runoff_mm > self.precipitation_mm:
            raise ValueError("surface runoff cannot exceed supplied local precipitation; lateral inflow is unsupported")


def stress_coefficient(root_zone, depletion_mm):
    if not isinstance(root_zone, RootZone):
        raise ValueError("explicit RootZone required")
    depletion = number(depletion_mm, "root-zone depletion")
    taw = root_zone.available_water_mm
    if depletion > taw:
        raise ValueError("depletion exceeds total available water")
    raw = root_zone.depletion_fraction * taw
    if depletion <= raw:
        return 1.0
    return (taw-depletion)/(taw-raw)


def water_balance(root_zone, daily_forcing, *, initial_depletion_mm):
    if not isinstance(root_zone, RootZone):
        raise ValueError("explicit RootZone required")
    if not isinstance(daily_forcing, (list, tuple)) or not 1 <= len(daily_forcing) <= 366:
        raise ValueError("supply 1..366 explicit daily forcing records for one representative crop season")
    if any(not isinstance(day, DayForcing) for day in daily_forcing):
        raise ValueError("daily inputs must be DayForcing records")
    initial = number(initial_depletion_mm, "initial depletion")
    stress_coefficient(root_zone, initial)
    taw = root_zone.available_water_mm
    depletion = initial
    rows = []
    for index, day in enumerate(daily_forcing):
        ks = stress_coefficient(root_zone, depletion)
        incoming = number(math.fsum((day.precipitation_mm-day.runoff_mm, day.net_irrigation_mm,
                                     day.capillary_rise_mm)), "daily water inflow")
        available = number(math.fsum((taw, -depletion, incoming)), "daily available water")
        et = min(number(ks*day.potential_crop_et_mm, "daily stressed ET"), available)
        raw_depletion = math.fsum((depletion, -incoming, et))
        drainage = max(0.0, -raw_depletion)
        following = max(0.0, raw_depletion)
        if following > taw:
            if following-taw > 8*math.ulp(taw):
                raise ArithmeticError("root-zone stock limit exceeded")
            following = taw  # representational residual remains in the explicit ledger
        residual = math.fsum((taw-depletion, incoming, -et, -drainage, -(taw-following)))
        scale = max(taw, incoming, et, drainage)
        if not math.isfinite(residual) or abs(residual) > 16*math.ulp(scale):
            raise ArithmeticError("daily water ledger does not reconcile")
        rows.append({"day": index+1, "initial_depletion_mm": depletion, "stress_coefficient": ks,
                     "actual_et_mm": et, "potential_et_mm": day.potential_crop_et_mm,
                     "inflow_mm": incoming, "deep_percolation_mm": drainage,
                     "final_depletion_mm": following, "water_residual_mm": residual})
        depletion = following
    totals = {"actual_et_mm": math.fsum(r["actual_et_mm"] for r in rows),
              "potential_et_mm": math.fsum(r["potential_et_mm"] for r in rows),
              "inflow_mm": math.fsum(r["inflow_mm"] for r in rows),
              "deep_percolation_mm": math.fsum(r["deep_percolation_mm"] for r in rows),
              "net_irrigation_mm": math.fsum(d.net_irrigation_mm for d in daily_forcing),
              "precipitation_mm": math.fsum(d.precipitation_mm for d in daily_forcing),
              "runoff_mm": math.fsum(d.runoff_mm for d in daily_forcing),
              "capillary_rise_mm": math.fsum(d.capillary_rise_mm for d in daily_forcing)}
    for key, value in totals.items():
        number(value, key)
    residual = math.fsum((taw-initial, totals["inflow_mm"], -totals["actual_et_mm"],
                          -totals["deep_percolation_mm"], -(taw-depletion)))
    scale = max(taw, totals["inflow_mm"], totals["actual_et_mm"], totals["deep_percolation_mm"])
    if abs(residual) > 32*len(rows)*math.ulp(scale):
        raise ArithmeticError("seasonal water ledger does not reconcile")
    return {"schema": "diadem.root-zone-water.r1", "rows": rows, "totals": totals,
            "initial_depletion_mm": initial, "final_depletion_mm": depletion,
            "total_available_water_mm": taw, "water_residual_mm": residual,
            "net_irrigation_m3_m2": totals["net_irrigation_mm"]/1000,
            "root_zone_evidence": root_zone.evidence, "root_zone_source_status": root_zone.source_status,
            "scope": "fixed-root daily single-coefficient well-drained nonsaline scenario; start-of-day stress"}


def crop_season(root_zone, daily_forcing, *, initial_depletion_mm, potential_yield_kg_m2,
                yield_response_factor, minimum_valid_et_ratio, evidence, source_status):
    """Supplied potential yield reduced by the published seasonal Ky relation.

    A physical/application lower ET-ratio bound is mandatory. Negative predicted
    yield or an unsupported severe deficit is OUTSIDE_REGIME, never silently
    clipped to zero. Unknown crop evidence produces UNKNOWN, not no food.
    This does not address salinity, nutrition, phenology, waterlogging or labour.
    """
    provenance(evidence, source_status)
    # Malformed known coefficients are invalid even when another is unknown.
    coefficients = {}
    for name, value in (("potential_yield_kg_m2", potential_yield_kg_m2),
                        ("yield_response_factor", yield_response_factor),
                        ("minimum_valid_et_ratio", minimum_valid_et_ratio)):
        coefficients[name] = None if value is None else number(value, name)
    if coefficients["minimum_valid_et_ratio"] is not None and coefficients["minimum_valid_et_ratio"] > 1:
        raise ValueError("minimum valid ET ratio cannot exceed one")
    water = water_balance(root_zone, daily_forcing, initial_depletion_mm=initial_depletion_mm)
    result_status = ("SYNTHETIC TEST" if source_status == "SYNTHETIC TEST" and
                     root_zone.source_status == "SYNTHETIC TEST" else "WORKING NON-CANON")
    result = {"schema": "diadem.crop-water-yield.r1", "water": water, "evidence": evidence,
              "source_status": result_status, "parameter_source_status": source_status,
              "coefficients": coefficients, "yield_kg_m2": None,
              "net_irrigation_m3_m2": water["net_irrigation_m3_m2"],
              "scope": "one crop season; seasonal Ky estimate, not a yield ceiling or complete crop model"}
    missing = [key for key, value in coefficients.items() if value is None]
    if missing or source_status == "UNKNOWN":
        return dict(result, status="UNKNOWN", reasons=missing or ["crop evidence unresolved"])
    etc = water["totals"]["potential_et_mm"]
    if etc == 0:
        return dict(result, status="OUTSIDE_REGIME", reasons=["zero potential seasonal ET"])
    ratio = water["totals"]["actual_et_mm"]/etc
    factor = 1-coefficients["yield_response_factor"]*(1-ratio)
    if ratio < coefficients["minimum_valid_et_ratio"] or factor < 0:
        return dict(result, status="OUTSIDE_REGIME", actual_to_potential_et_ratio=ratio,
                    reasons=["water deficit is outside the explicitly supplied seasonal yield regime"])
    value = number(coefficients["potential_yield_kg_m2"]*factor, "seasonal predicted yield")
    return dict(result, status="MODELLED", yield_kg_m2=value, actual_to_potential_et_ratio=ratio,
                reasons=[], scientific_acceptance="NOT_ESTABLISHED_BY_NUMERICAL_TESTS")
