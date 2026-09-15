"""Static continuous land/irrigation allocation, not social or nutritional capacity.

The objective is maximum annual edible energy from supplied, applicable crop
regimes. Every parcel is a physical productive rectangle in one common metre
frame. Allocation does not invent yields, crops, rain, irrigation or population.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import sys
import types
import uuid

import numpy as np
import scipy
from scipy.optimize import linprog

STATUS = {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST", "UNKNOWN"}
OBJECTIVE = "MAXIMUM_ANNUAL_EDIBLE_ENERGY_NOT_NUTRITIONAL_CAPACITY_OR_SOCIAL_OPTIMUM"
FOOD_ROOT = Path(__file__).resolve().parents[1] / "scientific_foundation_r1"
FOOD_PINS = {
    "food.py": "09e4d3ad2119b07dbe6e9c9507eca71a92e6c666ff0a56e9213ec84a4a098632",
    "erosion.py": "e4d7b6307dd21bbc9716b966a77a2ec8e2bf2cf96609a1ea25d631e48056c204",
}


def real(value, name, *, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(name + " must be an explicit real quantity")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(name + " is outside finite range") from exc
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(name + " is outside finite non-negative range")
    return value


def identity(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " is required")


def provenance(evidence, status):
    identity(evidence, "evidence")
    if status not in STATUS:
        raise ValueError("unrecognised source status")


@dataclass(frozen=True)
class LandParcel:
    parcel_id: str
    bounds_m: tuple[float, float, float, float]
    water_pool_id: str | None
    evidence: str
    source_status: str

    def __post_init__(self):
        identity(self.parcel_id, "parcel_id")
        provenance(self.evidence, self.source_status)
        if self.water_pool_id is not None:
            identity(self.water_pool_id, "water_pool_id")
        if not isinstance(self.bounds_m, (tuple, list)) or len(self.bounds_m) != 4:
            raise ValueError("bounds_m requires xmin,ymin,xmax,ymax in a common metre frame")
        if any(isinstance(v, (bool, np.bool_)) or not isinstance(v, (int,float,np.integer,np.floating)) for v in self.bounds_m):
            raise ValueError("physical bounds must be real metre coordinates")
        values = tuple(float(v) for v in self.bounds_m)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("physical parcel bounds must be finite")
        if values[2] <= values[0] or values[3] <= values[1]:
            raise ValueError("productive rectangles must have positive area")
        object.__setattr__(self, "bounds_m", values)
        real(self.area_m2, "productive parcel area", positive=True)

    @property
    def area_m2(self):
        x0, y0, x1, y1 = self.bounds_m
        return (x1-x0)*(y1-y0)


@dataclass(frozen=True)
class WaterPool:
    pool_id: str
    available_withdrawal_m3_year: float | None
    evidence: str
    source_status: str

    def __post_init__(self):
        identity(self.pool_id, "pool_id")
        provenance(self.evidence, self.source_status)
        if self.available_withdrawal_m3_year is not None:
            object.__setattr__(self, "available_withdrawal_m3_year", real(self.available_withdrawal_m3_year, "available pool withdrawal"))


@dataclass(frozen=True)
class CropOption:
    option_id: str
    parcel_id: str
    crop_id: str
    attainable_yield_kg_m2_year: float | None
    edible_fraction: float | None
    loss_fraction: float | None
    edible_energy_kcal_kg: float | None
    net_irrigation_m3_m2_year: float | None
    irrigation_efficiency: float | None
    evidence: str
    source_status: str
    minimum_area_m2: float = 0.0
    maximum_area_m2: float | None = None
    applicability: str = "VALID"

    def __post_init__(self):
        for name in ("option_id", "parcel_id", "crop_id"):
            identity(getattr(self, name), name)
        provenance(self.evidence, self.source_status)
        for name in ("attainable_yield_kg_m2_year", "edible_fraction", "loss_fraction",
                     "edible_energy_kcal_kg", "net_irrigation_m3_m2_year", "irrigation_efficiency",
                     "minimum_area_m2", "maximum_area_m2"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, real(getattr(self, name), name))
        for name in ("edible_fraction", "loss_fraction", "irrigation_efficiency"):
            if getattr(self, name) is not None and getattr(self, name) > 1:
                raise ValueError(name + " cannot exceed one")
        if self.irrigation_efficiency == 0:
            raise ValueError("supplied irrigation efficiency must be strictly positive")
        if self.maximum_area_m2 is not None and self.minimum_area_m2 > self.maximum_area_m2:
            raise ValueError("minimum option area exceeds maximum")
        if self.applicability not in {"VALID", "UNKNOWN", "OUTSIDE_REGIME"}:
            raise ValueError("invalid crop applicability status")


def option_from_crop_season(*, season_result, option_id, parcel_id, crop_id,
                            edible_fraction, loss_fraction, edible_energy_kcal_kg,
                            irrigation_efficiency, evidence, source_status, one_crop_season_per_year,
                            minimum_area_m2=0.0, maximum_area_m2=None):
    """One annual crop cycle from agroclimate.crop_season; never multiply seasons.

    The caller supplies food composition, losses, delivery efficiency and proof
    that this modelled crop cycle is the declared annual production regime.
    """
    if not isinstance(season_result, dict):
        raise ValueError("actual crop-season result required")
    if season_result.get("schema") != "diadem.crop-water-yield.r1":
        raise ValueError("unsupported crop-season schema")
    if one_crop_season_per_year is not True:
        raise ValueError("explicit one modelled crop season per representative annual cycle is required")
    applicability = season_result.get("status")
    if applicability not in {"MODELLED", "UNKNOWN", "OUTSIDE_REGIME"}:
        raise ValueError("crop-season result has unsupported status")
    if source_status != season_result.get("source_status"):
        raise ValueError("crop-season source status must be preserved by the allocator")
    applicability = "VALID" if applicability == "MODELLED" else applicability
    evidence = evidence + "; ONE MODELLED CROP SEASON PER YEAR; crop-season result sha256=" + hashlib.sha256(
        json.dumps(season_result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return CropOption(option_id, parcel_id, crop_id,
                      season_result.get("yield_kg_m2"), edible_fraction, loss_fraction, edible_energy_kcal_kg,
                      season_result.get("net_irrigation_m3_m2"), irrigation_efficiency, evidence, source_status,
                      minimum_area_m2, maximum_area_m2, applicability)


def _food_module():
    """Execute exact retained food-budget bytes, including its pinned real guard."""
    raws = {name: (FOOD_ROOT/name).read_bytes() for name in FOOD_PINS}
    for name, raw in raws.items():
        if hashlib.sha256(raw).hexdigest() != FOOD_PINS[name]:
            raise ValueError("retained food model changed: " + name)
    name = "_generator_upgrade_bound_food_" + uuid.uuid4().hex
    package = types.ModuleType(name); package.__path__ = [str(FOOD_ROOT)]
    sys.modules[name] = package
    try:
        for child in ("erosion", "food"):
            module = types.ModuleType(name + "." + child)
            module.__file__ = str(FOOD_ROOT/(child+".py")); module.__package__ = name
            sys.modules[module.__name__] = module
            exec(compile(raws[child+".py"], module.__file__, "exec", dont_inherit=True), module.__dict__)
        return module
    finally:
        for key in (name, name+".erosion", name+".food"):
            sys.modules.pop(key,None)


def _sum(values):
    return real(math.fsum(values), "finite aggregate")


def _dual_upper_bound(energy, matrix, capacity, lower, upper, prices):
    """Exact-rational weak-duality bound for the supplied binary64 LP coefficients.

    Nonnegative resource prices need not be an exact solver dual. Compensating
    upper-bound prices make every column dual-feasible without a tolerance.
    """
    ep = [F(float(v)) for v in energy]
    ap = [[F(float(v)) for v in row] for row in matrix]
    yp = [F(max(0.0, float(v))) for v in prices]
    lp, up = [F(float(v)) for v in lower], [F(float(v)) for v in upper]
    base = sum(e*l for e, l in zip(ep, lp))
    for row, cap, price in zip(ap, capacity, yp):
        base += price*(F(float(cap))-sum(a*l for a, l in zip(row, lp)))
    for j, (e, lo, hi) in enumerate(zip(ep, lp, up)):
        penalty = max(F(0), e-sum(row[j]*p for row, p in zip(ap, yp)))
        base += penalty*(hi-lo)
    value = float(base)
    if F(value) < base:
        value = math.nextafter(value, math.inf)
    return real(value, "dual energy upper bound")


def allocate_land_food(parcels, options, water_pools, *, frame_id,
                       annual_energy_kcal_per_person, fixed_population,
                       relative_optimality_tolerance=1e-8):
    """Allocate actual land and shared gross irrigation, then run the food budget.

    Inputs describe one fixed annual regime, uniformly productive within each
    rectangle. Continuous crop areas are allowed. Zero minimum area and omitted
    maximum (meaning the parcel area) are mathematical bounds, not crop facts.
    UNKNOWN/OUTSIDE_REGIME/INFEASIBLE/NUMERICAL_FAILURE return no fabricated supply.
    """
    identity(frame_id, "common physical metre frame_id")
    real(annual_energy_kcal_per_person, "annual energy need", positive=True)
    if type(fixed_population) is not int or fixed_population < 0:
        raise ValueError("fixed population must be a non-negative demand-only integer")
    tol = real(relative_optimality_tolerance, "relative optimality tolerance", positive=True)
    if tol > 1e-4:
        raise ValueError("numerical optimality tolerance must not conceal material allocation error")
    for values, cls, cap in ((parcels, LandParcel, 256), (options, CropOption, 512), (water_pools, WaterPool, 256)):
        if not isinstance(values, (tuple, list)) or len(values) > cap or any(not isinstance(v, cls) for v in values):
            raise ValueError("bounded typed physical inputs required")
    parcels = sorted(parcels, key=lambda p: p.parcel_id)
    options = sorted(options, key=lambda o: (o.parcel_id, o.option_id))
    water_pools = sorted(water_pools, key=lambda p: p.pool_id)
    pmap = {p.parcel_id:p for p in parcels}; wmap = {p.pool_id:p for p in water_pools}
    if len(pmap) != len(parcels) or len(wmap) != len(water_pools) or len({o.option_id for o in options}) != len(options):
        raise ValueError("duplicate identity would double-count land, water or crops")
    for i, parcel in enumerate(parcels):
        if parcel.water_pool_id is not None and parcel.water_pool_id not in wmap:
            raise ValueError("parcel references missing water pool")
        a = parcel.bounds_m
        for other in parcels[:i]:
            b = other.bounds_m
            if min(a[2],b[2]) > max(a[0],b[0]) and min(a[3],b[3]) > max(a[1],b[1]):
                raise ValueError("productive parcel interiors overlap: " + parcel.parcel_id + "/" + other.parcel_id)
    for option in options:
        if option.parcel_id not in pmap:
            raise ValueError("crop references missing physical parcel")
    payload = {"parcels":[asdict(p) for p in parcels], "options":[asdict(o) for o in options],
               "water_pools":[asdict(w) for w in water_pools], "frame_id":frame_id}
    source_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    result = {"schema":"diadem.static-land-food-allocation.r1", "objective":OBJECTIVE,
              "physical_input_sha256":source_id, "frame_id":frame_id, "status":None,
              "allocations":None, "food_budget":None, "water_ledger":None,
              "population_used_for_supply":False, "full_carrying_capacity":False,
              "source_pins":{str(FOOD_ROOT/k):v for k,v in FOOD_PINS.items()},
              "scope":"continuous area; one annual regime; no nutrition, labour, storage, transport, rotation or ecological reserve inference"}
    unknown = []
    for option in options:
        if option.applicability == "OUTSIDE_REGIME":
            return {**result, "status":"OUTSIDE_REGIME", "reason":"crop regime invalid: "+option.option_id}
        for field in ("attainable_yield_kg_m2_year", "edible_fraction", "loss_fraction", "edible_energy_kcal_kg",
                      "net_irrigation_m3_m2_year", "irrigation_efficiency"):
            if getattr(option, field) is None:
                unknown.append(option.option_id+"."+field)
        if option.applicability == "UNKNOWN" or option.source_status == "UNKNOWN":
            unknown.append(option.option_id+".applicability_or_source")
    for pool in water_pools:
        if pool.available_withdrawal_m3_year is None or pool.source_status == "UNKNOWN":
            unknown.append(pool.pool_id+".available_withdrawal")
    for parcel in parcels:
        if parcel.source_status == "UNKNOWN":
            unknown.append(parcel.parcel_id+".productive_land_authority")
    if unknown:
        return {**result, "status":"UNKNOWN", "unknown_fields":sorted(unknown)}
    count = len(options)
    area = np.array([pmap[o.parcel_id].area_m2 for o in options])
    lower = np.array([o.minimum_area_m2 for o in options])
    upper = np.array([min(pmap[o.parcel_id].area_m2, o.maximum_area_m2 if o.maximum_area_m2 is not None else pmap[o.parcel_id].area_m2) for o in options])
    energy = np.array([real(o.attainable_yield_kg_m2_year*o.edible_fraction*(1-o.loss_fraction)*o.edible_energy_kcal_kg, "energy density") for o in options])
    withdrawals = np.array([real(o.net_irrigation_m3_m2_year/o.irrigation_efficiency, "gross irrigation per area") for o in options])
    for j, option in enumerate(options):
        if pmap[option.parcel_id].water_pool_id is None and withdrawals[j] > 0:
            upper[j] = 0.0  # No supply connection: irrigated area is physically infeasible, not an invented rainfed yield.
    matrix=[];capacity=[]; labels=[]
    for parcel in parcels:
        matrix.append([float(o.parcel_id == parcel.parcel_id) for o in options])
        capacity.append(parcel.area_m2); labels.append("land:"+parcel.parcel_id)
    for pool in water_pools:
        matrix.append([withdrawals[j] if pmap[o.parcel_id].water_pool_id == pool.pool_id else 0.0 for j,o in enumerate(options)])
        capacity.append(pool.available_withdrawal_m3_year); labels.append("water:"+pool.pool_id)
    matrix = np.array(matrix, dtype=float).reshape(len(labels), count)
    capacity = np.array(capacity)
    violations = [options[j].option_id+".minimum_above_available_area" for j in range(count) if lower[j] > upper[j]]
    violations += [labels[k]+".minimum_demand_exceeds_stock" for k,row in enumerate(matrix)
                   if sum(F(float(a))*F(float(x)) for a,x in zip(row,lower)) > F(float(capacity[k]))]
    if violations:
        return {**result, "status":"INFEASIBLE", "reasons":violations}
    if count:
        objective_scale = float(np.max(energy*area)) or 1.0
        real(objective_scale, "LP objective scale", positive=True)
        row_scales = np.maximum(capacity, np.max(matrix*area[None,:], axis=1))
        row_scales[row_scales == 0] = 1.0
        normal_matrix = matrix*area[None,:]/row_scales[:,None]
        solution = linprog(-energy*area/objective_scale, A_ub=normal_matrix, b_ub=capacity/row_scales,
                           bounds=list(zip(lower/area,upper/area)), method="highs-ds",
                           options={"presolve":True,"primal_feasibility_tolerance":1e-9,
                                    "dual_feasibility_tolerance":1e-9,"simplex_dual_edge_weight_strategy":"steepest"})
        if not solution.success or not np.isfinite(solution.x).all():
            return {**result, "status":"NUMERICAL_FAILURE", "reason":str(solution.message)}
        allocated = np.clip(solution.x*area,lower,upper)
        # Correct only roundoff overdraw, always downwards toward the already feasible minimum.
        for row, cap in zip(matrix,capacity):
            used = _sum(row*allocated)
            if used > cap:
                if used-cap > tol*cap:
                    return {**result, "status":"NUMERICAL_FAILURE", "reason":"material primal stock violation"}
                fixed = _sum(row*lower); extra = _sum(row*(allocated-lower))
                factor = max(0.0, math.nextafter((cap-fixed)/extra,0.0)) if extra else 0.0
                selected = row > 0
                allocated[selected] = lower[selected]+(allocated[selected]-lower[selected])*factor
        prices = np.maximum(0,-np.asarray(solution.ineqlin.marginals))*objective_scale/row_scales
        upper_energy = _dual_upper_bound(energy,matrix,capacity,lower,upper,prices)
    else:
        allocated = np.zeros(0); upper_energy = 0.0
    food = _food_module(); food_parcels=[]; allocation_rows=[]
    cursors = {p.parcel_id:p.bounds_m[0] for p in parcels}
    for j, option in enumerate(options):
        planned = float(allocated[j]); parcel = pmap[option.parcel_id]
        x0,y0,x1,y1 = parcel.bounds_m; left = cursors[parcel.parcel_id]
        if planned == 0:
            continue
        right = min(x1, left+planned/(y1-y0))
        while right > left and (right-left)*(y1-y0) > planned:
            right = math.nextafter(right,left)
        achieved = (right-left)*(y1-y0)
        if achieved <= 0 or lower[j]-achieved > tol*lower[j]:
            return {**result, "status":"NUMERICAL_FAILURE", "reason":"allocated physical strip not representable at declared coordinates"}
        cursors[parcel.parcel_id] = right
        net = real(achieved*option.net_irrigation_m3_m2_year, "delivered irrigation")
        gross = real(achieved*withdrawals[j], "source withdrawal")
        food_parcels.append(food.FoodParcel(option.option_id,achieved,option.attainable_yield_kg_m2_year,
            option.edible_fraction,option.loss_fraction,option.edible_energy_kcal_kg,net,net,
            option.evidence+"; food water fields mean NET ROOT-ZONE IRRIGATION for the declared yield regime, not total ET", option.source_status))
        allocation_rows.append({"option_id":option.option_id,"crop_id":option.crop_id,"parcel_id":option.parcel_id,
            "water_pool_id":parcel.water_pool_id,"bounds_m":[left,y0,right,y1],"allocated_area_m2":achieved,
            "net_irrigation_m3_year":net,"gross_withdrawal_m3_year":gross,
            "delivery_loss_m3_year":gross-net,"planned_area_m2_before_geometric_rounding":planned})
    water=[]
    for pool in water_pools:
        rows=[r for r in allocation_rows if r["water_pool_id"] == pool.pool_id]
        used=_sum(r["gross_withdrawal_m3_year"] for r in rows)
        if used > pool.available_withdrawal_m3_year:
            return {**result,"status":"NUMERICAL_FAILURE","reason":"represented irrigation overdraw"}
        water.append({"pool_id":pool.pool_id,"available_withdrawal_m3_year":pool.available_withdrawal_m3_year,
            "withdrawal_m3_year":used,"unwithdrawn_m3_year":pool.available_withdrawal_m3_year-used,
            "delivered_irrigation_m3_year":_sum(r["net_irrigation_m3_year"] for r in rows),
            "delivery_loss_m3_year":_sum(r["delivery_loss_m3_year"] for r in rows)})
    budget=food.food_budget(food_parcels,available_land_m2=_sum(p.area_m2 for p in parcels),
                           annual_energy_kcal_per_person=annual_energy_kcal_per_person,fixed_population=fixed_population)
    achieved_energy=budget["total_available_energy_kcal_year"]
    gap=max(0.0,upper_energy-achieved_energy)
    if gap > tol*upper_energy or achieved_energy-upper_energy > tol*upper_energy:
        return {**result,"status":"NUMERICAL_FAILURE","reason":"independent dual energy-gap gate failed",
                "energy_upper_bound_kcal_year":upper_energy,"achieved_energy_kcal_year":achieved_energy}
    for name, expected in FOOD_PINS.items():
        if hashlib.sha256((FOOD_ROOT/name).read_bytes()).hexdigest() != expected:
            raise ValueError("food dependency changed during allocation")
    return {**result,"status":"OPTIMAL","allocations":allocation_rows,"food_budget":budget,"water_ledger":water,
            "solver":{"method":"highs-ds","scipy_version":scipy.__version__,
                "ordering":"parcel_id then option_id; canonical row order; fixed dual-simplex strategy",
                "tie_meaning":"one deterministic current-runtime optimum; not unique physical/social truth",
                "relative_optimality_tolerance":tol,"energy_upper_bound_kcal_year":upper_energy,
                "achieved_energy_kcal_year":achieved_energy,"certified_gap_kcal_year":gap,
                "certificate":"exact-rational weak duality for supplied binary64 physical LP coefficients"}}
