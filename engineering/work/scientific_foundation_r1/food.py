"""Independent physical food/land budget; no supply generated from population.

This is an accounting boundary, not a crop-yield or land-allocation predictor.
Supplied yields must apply to the declared water regime; deficient water rejects
instead of inventing a universal linear drought response. Unknown yield remains
unknown. The energy ceiling is not a nutritionally complete carrying capacity.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from .erosion import real


@dataclass(frozen=True)
class FoodParcel:
    parcel_id: str
    allocated_area_m2: float
    attainable_yield_kg_m2_year: float | None
    edible_fraction: float
    loss_fraction: float
    edible_energy_kcal_kg: float
    crop_water_requirement_m3_year: float
    crop_water_available_m3_year: float | None
    evidence: str
    source_status: str

    def __post_init__(self):
        if not isinstance(self.parcel_id, str) or not self.parcel_id.strip() or not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("parcel identity and yield/water evidence required")
        if self.source_status not in {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST", "UNKNOWN"}:
            raise ValueError("unsupported food source status")
        for key in ("allocated_area_m2", "edible_fraction", "loss_fraction", "edible_energy_kcal_kg", "crop_water_requirement_m3_year"):
            object.__setattr__(self, key, real(getattr(self, key), key))
        for key in ("attainable_yield_kg_m2_year", "crop_water_available_m3_year"):
            if getattr(self, key) is not None:
                object.__setattr__(self, key, real(getattr(self, key), key))
        if max(self.edible_fraction, self.loss_fraction) > 1:
            raise ValueError("edible/loss fractions must not exceed one")
        if self.source_status == "UNKNOWN" and self.attainable_yield_kg_m2_year is not None:
            raise ValueError("unknown yield must not be encoded as a known quantity")


def food_budget(parcels, *, available_land_m2, annual_energy_kcal_per_person, fixed_population):
    """Annual energy accounting with explicit non-overlapping allocated parcels.

    Caller must establish parcel disjointness and shared-water allocation before
    this boundary. A total-area check cannot discover overlapping geometries.
    fixed_population is demand only: never overwritten or used to create supply.
    """
    land = real(available_land_m2, "available land")
    need = real(annual_energy_kcal_per_person, "annual energy need", positive=True)
    if type(fixed_population) is not int or fixed_population < 0:
        raise ValueError("fixed population must be a non-negative integer")
    if not isinstance(parcels, (list, tuple)) or len(parcels) > 65536 or any(not isinstance(x, FoodParcel) for x in parcels):
        raise ValueError("bounded explicit food parcels required")
    if len({p.parcel_id for p in parcels}) != len(parcels):
        raise ValueError("duplicate parcel would double-count food")
    allocated = math.fsum(p.allocated_area_m2 for p in parcels)
    if allocated > land:
        raise ValueError("allocated crop area exceeds independent land stock")
    unknown = []
    rows = []
    for p in parcels:
        if p.attainable_yield_kg_m2_year is None or p.crop_water_available_m3_year is None:
            unknown.append(p.parcel_id)
            continue
        if p.crop_water_available_m3_year < p.crop_water_requirement_m3_year:
            raise ValueError("yield water regime unsupported for parcel " + p.parcel_id)
        harvest = real(p.allocated_area_m2 * p.attainable_yield_kg_m2_year, "annual harvest")
        edible = real(harvest * p.edible_fraction, "edible harvest")
        losses = real(edible * p.loss_fraction, "food losses")
        delivered = edible - losses
        energy = real(delivered * p.edible_energy_kcal_kg, "annual edible energy")
        rows.append({"parcel_id": p.parcel_id, "harvest_kg_year": harvest, "non_edible_kg_year": harvest-edible,
                     "loss_kg_year": losses, "available_food_kg_year": delivered, "available_energy_kcal_year": energy,
                     "mass_residual_kg_year": math.fsum([harvest, -(harvest-edible), -losses, -delivered]),
                     "evidence": p.evidence, "source_status": p.source_status})
    known = real(math.fsum(r["available_energy_kcal_year"] for r in rows), "known energy")
    demand = real(need * fixed_population, "fixed demand")
    total = None if unknown else known
    equivalents = None if total is None else real(total/need, "energy-only person equivalents")
    return {"schema": "diadem.independent-food-energy-budget.r1", "rows": rows,
            "allocated_area_m2": allocated, "unallocated_area_m2": land-allocated,
            "unknown_parcel_ids": unknown, "known_energy_lower_bound_kcal_year": known,
            "total_available_energy_kcal_year": total,
            "energy_only_person_equivalents": equivalents,
            "fixed_population": fixed_population, "energy_demand_kcal_year": demand,
            "energy_balance_kcal_year": None if total is None else total-demand,
            "independent_of_population_prior": True, "full_carrying_capacity": False,
            "scope": "energy budget; excludes nutrition, storage seasonality, labour and transport capacity"}
