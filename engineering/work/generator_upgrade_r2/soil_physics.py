"""Owner-defined bounded soil properties, layered Darcy flow and shallow FS.

Operational horizons are supplied pedological hypotheses, never inferred from
stored rock layers or suitability codes. See SOIL_DESIGN.md for support limits.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import math
from pathlib import Path


OWNER_PATH = Path("C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/02_Working_Files/Geography/Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-10-R1/CLIMATE_SOILS_OWNER_DECISION_2026-09-10_R1.md")
OWNER_SHA256 = "ba909d8a3e34a1722cba51925d602eca28d749a91a7bbf2162baf99221b4de19"
HORIZONS = frozenset("OAEBCR")
KNOWN_STATUS = {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST"}
MISSING_STATUS = {"UNKNOWN", "INCOMPLETE", "CONFLICT"}
MAX_LAYERS = 128
MAX_GRID_CELLS = 4096
MAX_CASES_PER_CELL = 32


def verify_owner_binding():
    if hashlib.sha256(OWNER_PATH.read_bytes()).hexdigest() != OWNER_SHA256:
        raise ValueError("soil owner definition changed; guarded rebind required")


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + " requires bounded nonempty evidence/identity")


def _number(value, name):
    if type(value) not in (int, float):
        raise ValueError(name + " requires a finite int/float, not a score/object/bool")
    try:
        answer = float(value)
    except OverflowError as error:
        raise ValueError(name + " exceeds supported numeric range") from error
    if not math.isfinite(answer):
        raise ValueError(name + " must be finite")
    return answer


@dataclass(frozen=True)
class Interval:
    lower: float | None
    upper: float | None
    unit: str
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.unit, "unit")
        _text(self.evidence, "quantity evidence")
        if self.lower is None or self.upper is None:
            if self.lower is not None or self.upper is not None or self.source_status not in MISSING_STATUS:
                raise ValueError("missing quantities require two null endpoints and unresolved status")
        else:
            lower = _number(self.lower, "lower endpoint")
            upper = _number(self.upper, "upper endpoint")
            if lower > upper or self.source_status not in KNOWN_STATUS:
                raise ValueError("ordered interval and explicit known source status required")
            object.__setattr__(self, "lower", lower)
            object.__setattr__(self, "upper", upper)

    @property
    def known(self):
        return self.lower is not None

    def as_dict(self):
        return asdict(self)


def _check(value, unit, name, *, minimum=None, positive=False):
    if type(value) is not Interval or value.unit != unit:
        raise ValueError(name + " has the wrong physical quantity/units")
    if value.known and ((positive and value.lower <= 0) or (minimum is not None and value.lower < minimum)):
        raise ValueError(name + " outside supported physical range")
    return value


def _unknown(unit, reason, status="UNKNOWN"):
    return Interval(None, None, unit, reason, status)


def _endpoint(value, lower):
    try:
        answer = float(value)
    except OverflowError as error:
        raise ValueError("derived physical interval is not representable") from error
    if not math.isfinite(answer):
        raise ValueError("derived physical interval is not representable")
    if (lower and Fraction(answer) > value) or (not lower and Fraction(answer) < value):
        answer = math.nextafter(answer, -math.inf if lower else math.inf)
    if not math.isfinite(answer):
        raise ValueError("outward interval endpoint is not representable")
    return answer


def _derived(lower, upper, unit, evidence, inputs=()):
    status = "SYNTHETIC TEST" if inputs and all(x.source_status == "SYNTHETIC TEST" for x in inputs) else "WORKING NON-CANON"
    return Interval(_endpoint(Fraction(lower), True), _endpoint(Fraction(upper), False), unit, evidence, status)


def _sum(values, unit, evidence):
    if any(not value.known for value in values):
        return _unknown(unit, evidence + "; at least one constituent is unresolved")
    return _derived(sum((Fraction(v.lower) for v in values), Fraction()),
                    sum((Fraction(v.upper) for v in values), Fraction()), unit, evidence, values)


@dataclass(frozen=True)
class Support:
    kind: str
    output_resolution_m: float | None
    process_support_m: float | None
    scenario_id: str
    evidence: str

    def __post_init__(self):
        if self.kind not in {"SCALAR_REFERENCE", "REPRESENTATIVE_SLOPE", "SUBGRID_CASE", "CELL_MEAN"}:
            raise ValueError("explicit physical/spatial support kind required")
        _text(self.scenario_id, "scenario identity")
        _text(self.evidence, "support evidence")
        for field in ("output_resolution_m", "process_support_m"):
            value = getattr(self, field)
            if value is not None:
                value = _number(value, field)
                if value <= 0:
                    raise ValueError("support lengths must be positive")
                object.__setattr__(self, field, value)
        if self.kind != "SCALAR_REFERENCE" and (self.output_resolution_m is None or self.process_support_m is None):
            raise ValueError("mapped cases require output resolution and actual process support")


@dataclass(frozen=True)
class Horizon:
    horizon_id: str
    candidates: tuple[str, ...]
    thickness_m: Interval
    ksat_horizontal_m_s: Interval
    ksat_vertical_m_s: Interval
    evidence: str

    def __post_init__(self):
        _text(self.horizon_id, "horizon identity")
        _text(self.evidence, "horizon interpretation evidence")
        if type(self.candidates) is not tuple or len(set(self.candidates)) != len(self.candidates) or any(x not in HORIZONS for x in self.candidates):
            raise ValueError("unique O/A/E/B/C/R alternatives, or an empty tuple for UNKNOWN, required")
        _check(self.thickness_m, "m", "horizon thickness", positive=True)
        _check(self.ksat_horizontal_m_s, "m/s", "horizontal Ksat", minimum=0)
        _check(self.ksat_vertical_m_s, "m/s", "vertical Ksat", minimum=0)


@dataclass(frozen=True)
class SoilProfile:
    profile_id: str
    horizons: tuple[Horizon, ...]
    absent_horizons: tuple[tuple[str, str], ...]
    solum_absence_evidence: str | None
    rooting_depth_m: Interval
    unconsolidated_thickness_m: Interval
    weathered_regolith_thickness_m: Interval
    support: Support
    evidence: str

    def __post_init__(self):
        _text(self.profile_id, "profile identity")
        _text(self.evidence, "profile evidence")
        if type(self.horizons) is not tuple or len(self.horizons) > MAX_LAYERS or any(type(h) is not Horizon for h in self.horizons):
            raise ValueError("bounded ordered horizon sequence required")
        if len({h.horizon_id for h in self.horizons}) != len(self.horizons):
            raise ValueError("duplicate horizon identity")
        if type(self.absent_horizons) is not tuple or len(self.absent_horizons) > 6:
            raise ValueError("explicit absent-horizon evidence required")
        absence = {}
        for item in self.absent_horizons:
            if type(item) is not tuple or len(item) != 2 or item[0] not in HORIZONS or item[0] in absence:
                raise ValueError("invalid/duplicate absent horizon declaration")
            _text(item[1], "absence evidence")
            absence[item[0]] = item[1]
        possible = set().union(*(set(h.candidates) for h in self.horizons))
        if possible.intersection(absence):
            raise ValueError("a horizon cannot be both absent and present/possible")
        if self.solum_absence_evidence is not None:
            _text(self.solum_absence_evidence, "explicit absent-solum evidence")
            if possible.intersection("AEB"):
                raise ValueError("absent solum conflicts with possible pedogenic horizons")
        for name in ("rooting_depth_m", "unconsolidated_thickness_m", "weathered_regolith_thickness_m"):
            _check(getattr(self, name), "m", name, minimum=0)
        if type(self.support) is not Support:
            raise ValueError("profile support required")


def profile_outputs(profile):
    """Construct operational horizon geometry and distinct owner-defined depths.

    Horizons are ordered downwards from the actual ground surface. No fixed
    O-A-E-B-C-R ordering is imposed: absent, repeated/buried and uncertain
    horizons are retained. Ambiguous genetic interpretation is not a taxonomy.
    """
    verify_owner_binding()
    if type(profile) is not SoilProfile:
        raise ValueError("SoilProfile required; rock stock layers are not horizons")
    rows = []
    cumulative = []
    rock_candidates = []
    for horizon in profile.horizons:
        top = _sum(cumulative, "m", "depth below ground surface")
        cumulative.append(horizon.thickness_m)
        bottom = _sum(cumulative, "m", "depth below ground surface")
        rows.append({"horizon_id": horizon.horizon_id, "candidates": list(horizon.candidates),
                     "interpretation_mask": "UNKNOWN" if not horizon.candidates else ("PRESENT" if len(horizon.candidates) == 1 else "AMBIGUOUS"),
                     "top_depth_m": top.as_dict(), "bottom_depth_m": bottom.as_dict(),
                     "thickness_m": horizon.thickness_m.as_dict(), "evidence": horizon.evidence,
                     "ksat_horizontal_m_s": horizon.ksat_horizontal_m_s.as_dict(),
                     "ksat_vertical_m_s": horizon.ksat_vertical_m_s.as_dict()})
        if not horizon.candidates or "R" in horizon.candidates:
            rock_candidates.append((horizon, top))
    presence = {}
    absence = dict(profile.absent_horizons)
    for code in sorted(HORIZONS):
        relevant = [h for h in profile.horizons if code in h.candidates]
        if any(h.candidates == (code,) for h in relevant):
            presence[code] = "PRESENT"
        elif relevant:
            presence[code] = "AMBIGUOUS"
        else:
            presence[code] = "ABSENT" if code in absence else "UNKNOWN"
    prefix = []
    mineral_start = None
    for index, horizon in enumerate(profile.horizons):
        if not horizon.candidates:
            break
        elif horizon.candidates == ("O",):
            prefix.append(horizon.thickness_m)
        elif "O" in horizon.candidates:
            break
        else:
            mineral_start = index
            break
    organic = (_sum(prefix, "m", "surface organic horizon thickness, separate from mineral solum")
               if mineral_start is not None else _unknown("m", "surface organic/mineral boundary not established"))
    solum = _unknown("m", "mineral surface or first C/R contact not established")
    solum_mask = "UNKNOWN"
    if profile.solum_absence_evidence is not None:
        solum = _derived(0, 0, "m", "explicit absent solum: " + profile.solum_absence_evidence)
        solum_mask = "EXPLICIT_ABSENCE"
    elif mineral_start is not None:
        pedogenic = []
        for horizon in profile.horizons[mineral_start:]:
            alternatives = set(horizon.candidates)
            if not alternatives:
                solum = _unknown("m", "unclassified horizon may contain the first parent boundary")
                break
            if alternatives <= {"C", "R"}:
                if pedogenic:
                    solum = _sum(pedogenic, "m", "mineral surface to top of first modelled C/R")
                    solum_mask = "VALID" if solum.known else "UNKNOWN"
                else:
                    solum = _unknown("m", "zero mineral solum requires explicit absent-solum evidence")
                break
            if not alternatives <= {"A", "E", "B"}:
                solum_mask = "AMBIGUOUS"
                solum = _unknown("m", "uncertain parent contact or buried organic horizon requires an explicit profile scenario")
                break
            pedogenic.append(horizon.thickness_m)
    rock = _unknown("m", "depth to R rock not established within described profile")
    if rock_candidates:
        first, top = rock_candidates[0]
        if first.candidates == ("R",):
            rock = top
    return {"schema": "diadem.operational-soil-profile.r2", "profile_id": profile.profile_id,
            "owner_sha256": OWNER_SHA256, "source_status": "WORKING NON-CANON",
            "support": asdict(profile.support), "evidence": profile.evidence,
            "horizons": rows, "horizon_presence": presence, "absence_evidence": absence,
            "mineral_solum_thickness_m": solum.as_dict(), "solum_mask": solum_mask,
            "surface_organic_thickness_m": organic.as_dict(), "depth_to_rock_from_ground_m": rock.as_dict(),
            "rooting_depth_m": profile.rooting_depth_m.as_dict(),
            "unconsolidated_thickness_m": profile.unconsolidated_thickness_m.as_dict(),
            "weathered_regolith_thickness_m": profile.weathered_regolith_thickness_m.as_dict(),
            "fertility": {"value": None, "mask": "NOT_IMPLEMENTED", "reason": "no nutrient-supply/retention model is selected here"},
            "limitations": "operational supplied pedological hypotheses; not soil formation, surveyed horizons or accepted taxonomy"}


@dataclass(frozen=True)
class ConductivityLayer:
    layer_id: str
    thickness_m: Interval
    horizontal_m_s: Interval
    vertical_m_s: Interval

    def __post_init__(self):
        _text(self.layer_id, "hydraulic layer identity")
        _check(self.thickness_m, "m", "hydraulic layer thickness", positive=True)
        _check(self.horizontal_m_s, "m/s", "horizontal saturated conductivity", minimum=0)
        _check(self.vertical_m_s, "m/s", "vertical saturated conductivity", minimum=0)


def ksat_um_s_to_m_s(value):
    _check(value, "um/s", "hydraulic conductivity", minimum=0)
    if not value.known:
        return _unknown("m/s", value.evidence, value.source_status)
    return _derived(Fraction(value.lower)/1_000_000, Fraction(value.upper)/1_000_000, "m/s",
                    "explicit micrometre/second to metre/second conversion: " + value.evidence, (value,))


@dataclass(frozen=True)
class Fluid:
    density_kg_m3: Interval
    dynamic_viscosity_pa_s: Interval
    gravity_m_s2: Interval
    temperature_kelvin: Interval
    composition: str
    evidence: str

    def __post_init__(self):
        _check(self.density_kg_m3, "kg/m3", "fluid density", positive=True)
        _check(self.dynamic_viscosity_pa_s, "Pa*s", "dynamic viscosity", positive=True)
        _check(self.gravity_m_s2, "m/s2", "gravity", positive=True)
        _check(self.temperature_kelvin, "K", "fluid temperature", positive=True)
        _text(self.composition, "fluid composition")
        _text(self.evidence, "consistent fluid-property evidence")


def intrinsic_permeability(ksat, fluid):
    """k=K*mu/(rho*g); not a numerical relabelling of hydraulic conductivity."""
    verify_owner_binding()
    _check(ksat, "m/s", "saturated hydraulic conductivity", minimum=0)
    if type(fluid) is not Fluid:
        raise ValueError("explicit fluid state/assumptions required")
    rho, mu, gravity = fluid.density_kg_m3, fluid.dynamic_viscosity_pa_s, fluid.gravity_m_s2
    inputs = (ksat, rho, mu, gravity, fluid.temperature_kelvin)
    if any(not v.known for v in inputs):
        return _unknown("m2", "conductivity or required consistent fluid assumptions unresolved")
    low = Fraction(ksat.lower)*Fraction(mu.lower)/(Fraction(rho.upper)*Fraction(gravity.upper))
    high = Fraction(ksat.upper)*Fraction(mu.upper)/(Fraction(rho.lower)*Fraction(gravity.lower))
    return _derived(low, high, "m2", "k=K*mu/(rho*g); " + fluid.composition + "; " + fluid.evidence, inputs)


def layered_ksat(layers):
    """Steady saturated Darcy equivalents for parallel planar homogeneous layers.

    Horizontal is arithmetic thickness-weighted; vertical is harmonic. These
    are not root-zone drainage, unsaturated conductivity or a rotated tensor.
    """
    verify_owner_binding()
    if type(layers) not in (tuple, list) or not 0 < len(layers) <= MAX_LAYERS or any(type(x) is not ConductivityLayer for x in layers):
        raise ValueError("bounded explicit hydraulic-layer inventory required")
    if len({x.layer_id for x in layers}) != len(layers):
        raise ValueError("duplicate hydraulic layer identity")
    thickness = [x.thickness_m for x in layers]
    outputs = {}
    for direction in ("horizontal", "vertical"):
        conductivities = [getattr(x, direction + "_m_s") for x in layers]
        if any(not x.known for x in thickness + conductivities):
            result = _unknown("m/s", direction + " Darcy equivalent has unresolved layer properties")
        else:
            hlow = sum(Fraction(x.lower) for x in thickness)
            hhigh = sum(Fraction(x.upper) for x in thickness)
            if direction == "horizontal":
                low = sum(Fraction(h.lower)*Fraction(k.lower) for h, k in zip(thickness, conductivities))/hhigh
                high = sum(Fraction(h.upper)*Fraction(k.upper) for h, k in zip(thickness, conductivities))/hlow
            else:
                low = (Fraction() if any(k.lower == 0 for k in conductivities) else
                       hlow / sum(Fraction(h.upper)/Fraction(k.lower) for h, k in zip(thickness, conductivities)))
                high = (Fraction() if any(k.upper == 0 for k in conductivities) else
                        hhigh / sum(Fraction(h.lower)/Fraction(k.upper) for h, k in zip(thickness, conductivities)))
            # Preserve the exact weighted-mean range despite deliberately loose
            # interval dependency treatment for uncertain thicknesses.
            low = max(low, min(Fraction(k.lower) for k in conductivities))
            high = min(high, max(Fraction(k.upper) for k in conductivities))
            result = _derived(low, high, "m/s", direction + " saturated planar-layer Darcy equivalent", thickness+conductivities)
        outputs[direction + "_m_s"] = result.as_dict()
    return {"schema": "diadem.layered-darcy-equivalent.r2", "owner_sha256": OWNER_SHA256,
            "directions": "horizontal parallel to layering; vertical normal to horizontal layering",
            "layer_inputs": [asdict(x) for x in layers], **outputs,
            "interval_meaning": "conservative Cartesian input-range enclosure; no probability or calibrated uncertainty distribution"}


@dataclass(frozen=True)
class Roots:
    basal_cohesion_pa: Interval
    maximum_active_depth_m: Interval
    mode: str
    evidence: str

    def __post_init__(self):
        _check(self.basal_cohesion_pa, "Pa", "basal root cohesion", minimum=0)
        _check(self.maximum_active_depth_m, "m", "active root depth", minimum=0)
        if self.mode not in {"BASAL", "ABSENT", "LATERAL_ONLY", "UNKNOWN"}:
            raise ValueError("explicit basal/lateral/absent/unknown root geometry required")
        _text(self.evidence, "root strength/condition/orientation and depth evidence")
        if self.mode in {"ABSENT", "LATERAL_ONLY"} and (not self.basal_cohesion_pa.known or self.basal_cohesion_pa.upper != 0):
            raise ValueError("absent or lateral-only roots must explicitly supply zero basal cohesion")
        if self.mode == "ABSENT" and (not self.maximum_active_depth_m.known or self.maximum_active_depth_m.upper != 0):
            raise ValueError("explicitly absent roots require zero active rooting depth")


@dataclass(frozen=True)
class SlopeCase:
    case_id: str
    regime: str
    vertical_failure_depth_m: Interval
    slope_degrees: Interval
    bulk_unit_weight_n_m3: Interval
    effective_cohesion_pa: Interval
    effective_friction_degrees: Interval
    pore_pressure_pa: Interval
    roots: Roots
    support: Support
    water_state_id: str
    material_state_id: str
    evidence: str

    def __post_init__(self):
        _text(self.case_id, "slope case identity")
        if self.regime not in {"SHALLOW_TRANSLATIONAL_SOIL", "ROCKFALL", "DEEP_FAILURE", "OTHER", "UNKNOWN"}:
            raise ValueError("explicit failure regime required")
        for name in ("water_state_id", "material_state_id", "evidence"):
            _text(getattr(self, name), name)
        _check(self.vertical_failure_depth_m, "m", "vertical failure depth", positive=True)
        _check(self.slope_degrees, "degree", "slope", minimum=0)
        _check(self.bulk_unit_weight_n_m3, "N/m3", "actual bulk soil unit weight", positive=True)
        _check(self.effective_cohesion_pa, "Pa", "effective soil cohesion", minimum=0)
        _check(self.effective_friction_degrees, "degree", "effective friction angle", minimum=0)
        _check(self.pore_pressure_pa, "Pa", "Water-supplied pore pressure")
        for angle in (self.slope_degrees, self.effective_friction_degrees):
            if angle.known and angle.upper >= 90:
                raise ValueError("slope/friction angles must be below 90 degrees")
        if type(self.roots) is not Roots or type(self.support) is not Support:
            raise ValueError("root geometry and physical support contracts required")


def factor_of_safety(case):
    """Static shallow infinite slope with vertical depth and basal effective stress.

    FS=[c'+c_root+(gamma*z*cos(beta)^2-u)*tan(phi')]
       /[gamma*z*sin(beta)*cos(beta)]. No event frequency or failure probability.
    """
    verify_owner_binding()
    if type(case) is not SlopeCase:
        raise ValueError("SlopeCase required")
    result = {"schema": "diadem.shallow-soil-factor-of-safety.r2", "case_id": case.case_id,
              "owner_sha256": OWNER_SHA256, "source_status": "WORKING NON-CANON",
              "inputs": asdict(case), "factor_of_safety": None, "mask": "UNKNOWN", "reason": ""}
    if case.regime != "SHALLOW_TRANSLATIONAL_SOIL":
        result.update(mask="UNKNOWN" if case.regime == "UNKNOWN" else "INAPPLICABLE", reason="separate or unresolved failure regime")
        return result
    if case.support.kind == "CELL_MEAN":
        result.update(mask="INAPPLICABLE", reason="a cell-average slope is not a representative/subgrid failure geometry")
        return result
    quantities = {name: getattr(case, name) for name in ("vertical_failure_depth_m", "slope_degrees", "bulk_unit_weight_n_m3",
                                                       "effective_cohesion_pa", "effective_friction_degrees", "pore_pressure_pa")}
    missing = [name for name, value in quantities.items() if not value.known or value.lower != value.upper]
    if missing:
        result.update(reason="explicit joint point scenarios needed for missing/interval quantities", unresolved=missing)
        return result
    z, beta, gamma, cohesion, friction, pressure = [quantities[name].lower for name in quantities]
    if beta == 0:
        result.update(mask="INAPPLICABLE", reason="zero driving shear; no finite factor-of-safety ratio")
        return result
    if pressure < 0:
        result.update(mask="INAPPLICABLE", reason="negative pore pressure requires an explicit unsaturated effective-stress model")
        return result
    roots = case.roots
    root_flag = roots.mode
    root_cohesion = 0.0
    if roots.mode == "UNKNOWN":
        result.update(reason="root contribution/geometry unresolved")
        return result
    if roots.mode == "BASAL":
        below_roots = roots.maximum_active_depth_m.known and roots.maximum_active_depth_m.upper < z
        if below_roots:
            # This geometric exclusion is independent of unknown root strength.
            root_flag = "ROOTS_DO_NOT_REACH_FAILURE_PLANE"
        elif not roots.basal_cohesion_pa.known:
            result.update(reason="basal root strength unresolved")
            return result
        elif roots.basal_cohesion_pa.upper != 0:
            if not roots.maximum_active_depth_m.known or roots.maximum_active_depth_m.lower != roots.maximum_active_depth_m.upper:
                result.update(reason="point root depth scenario required")
                return result
            if roots.maximum_active_depth_m.lower < z:
                root_flag = "ROOTS_DO_NOT_REACH_FAILURE_PLANE"
            elif roots.basal_cohesion_pa.lower != roots.basal_cohesion_pa.upper:
                result.update(reason="point basal root-strength scenario required")
                return result
            else:
                root_cohesion = roots.basal_cohesion_pa.lower
    b = math.radians(beta)
    f = math.radians(friction)
    sine, cosine, tangent = map(Fraction, (math.sin(b), math.cos(b), math.tan(f)))
    if sine <= 0 or cosine <= 0:
        raise ValueError("slope geometry is not representable")
    if friction > 0 and tangent <= 0:
        raise ValueError("positive friction angle underflows representable trigonometry")
    weight = Fraction(gamma)*Fraction(z)
    normal = weight*cosine*cosine
    driving = weight*sine*cosine
    effective = normal-Fraction(pressure)
    if effective <= 0:
        result.update(mask="INAPPLICABLE", reason="loss of compressive effective normal stress; uplift/fluidisation is outside this model")
        return result
    resisting = Fraction(cohesion)+Fraction(root_cohesion)+effective*tangent
    fs = resisting/driving
    numerical = {}
    for name, value in (("factor_of_safety", fs), ("total_normal_stress_pa", normal), ("pore_pressure_pa", Fraction(pressure)),
                        ("effective_normal_stress_pa", effective), ("driving_shear_pa", driving), ("resisting_shear_pa", resisting)):
        try:
            answer = _number(float(value), name)
        except OverflowError as error:
            raise ValueError(name + " exceeds supported output range") from error
        if value and answer == 0:
            raise ValueError(name + " underflows supported output range")
        numerical[name] = answer
    result.update(**numerical, mask="VALID", reason="supported static prescribed shallow-soil case",
                  effective_basal_root_cohesion_pa=root_cohesion, root_geometry_flag=root_flag,
                  numerical_meaning="binary64 trigonometry; exact represented stress arithmetic; not a certified physical-error bound")
    return result


def stability_grid(shape, cells):
    """Bounded row-major grid of explicit coequal representative/subgrid cases."""
    if type(shape) is not tuple or len(shape) != 2 or any(type(x) is not int or x <= 0 for x in shape) or shape[0]*shape[1] > MAX_GRID_CELLS:
        raise ValueError("bounded positive two-dimensional grid shape required")
    if type(cells) is not tuple or len(cells) != shape[0]*shape[1]:
        raise ValueError("one immutable case tuple per row-major cell required")
    output = []
    resolutions = set()
    support_kinds = set()
    for cases in cells:
        if type(cases) is not tuple or not 0 < len(cases) <= MAX_CASES_PER_CELL or any(type(case) is not SlopeCase for case in cases):
            raise ValueError("each cell needs bounded explicit case(s), including UNKNOWN where unresolved")
        if len({case.case_id for case in cases}) != len(cases):
            raise ValueError("duplicate slope case identity in cell")
        resolutions.update(case.support.output_resolution_m for case in cases)
        support_kinds.update(case.support.kind for case in cases)
        results = [factor_of_safety(case) for case in cases]
        valid = [x["factor_of_safety"] for x in results if x["mask"] == "VALID"]
        complete = len(valid) == len(results)
        mask = "VALID" if complete else ("PARTIAL" if valid else ("INAPPLICABLE" if all(x["mask"] == "INAPPLICABLE" for x in results) else "UNKNOWN"))
        output.append({"mask": mask, "cases": results, "complete_for_supplied_cases": complete,
                       "known_case_minimum": min(valid) if valid else None,
                       "known_case_maximum": max(valid) if valid else None})
    if len(resolutions) != 1:
        raise ValueError("one output resolution/support frame per grid required")
    if "SCALAR_REFERENCE" in support_kinds and len(support_kinds) != 1:
        raise ValueError("indexed scalar references and mapped cases must remain separate")
    return {"schema": "diadem.shallow-soil-stability-grid.r2", "shape": list(shape), "cells": output,
            "output_resolution_m": next(iter(resolutions)),
            "support_mode": "INDEXED_SCALAR_REFERENCE_NOT_MAPPED" if support_kinds == {"SCALAR_REFERENCE"} else "DECLARED_REPRESENTATIVE_CASE_GRID",
            "owner_sha256": OWNER_SHA256, "scenario_meaning": "coequal explicit cases; extrema of known cases only, not probabilities or full uncertainty bounds"}


def verification_reference():
    """Small deterministic actually computed owner-definition/physics reference."""
    def q(value, unit):
        return Interval(value, value, unit, "independent synthetic reference", "SYNTHETIC TEST")
    unknown_m = _unknown("m", "no rooting/unconsolidated/regolith observation supplied")
    support = Support("SCALAR_REFERENCE", None, None, "soil-reference", "analytical fixture, no mapped Diadem values")
    horizons = tuple(Horizon(code+str(index), (code,), q(depth, "m"), q(k, "m/s"), q(k, "m/s"), "prescribed operational horizon")
                     for index, (code, depth, k) in enumerate((("O", .1, .0001), ("A", .2, .00001),
                                                              ("B", .3, .000001), ("C", 1, .000001), ("R", 1, .0000001))))
    profile = profile_outputs(SoilProfile("synthetic-profile", horizons, (("E", "explicitly absent in this fixture"),),
                                         None, unknown_m, unknown_m, unknown_m, support, "not inferred from material stocks"))
    hydraulic = layered_ksat((ConductivityLayer("fast", q(1, "m"), q(4, "m/s"), q(4, "m/s")),
                              ConductivityLayer("slow", q(3, "m"), q(1, "m/s"), q(1, "m/s"))))
    roots = Roots(q(500, "Pa"), q(2, "m"), "BASAL", "supplied basal reinforcement crosses the plane")
    case = SlopeCase("synthetic-slope", "SHALLOW_TRANSLATIONAL_SOIL", q(1, "m"), q(45, "degree"), q(20000, "N/m3"),
                     q(1000, "Pa"), q(45, "degree"), q(2000, "Pa"), roots, support, "synthetic-water", "synthetic-material", "vertical-depth static oracle")
    stability = factor_of_safety(case)
    if profile["solum_mask"] != "VALID" or not profile["mineral_solum_thickness_m"]["lower"] <= .5 <= profile["mineral_solum_thickness_m"]["upper"]:
        raise ArithmeticError("independent mineral-solum reference failed")
    if hydraulic["horizontal_m_s"]["lower"] != 1.75 or not hydraulic["vertical_m_s"]["lower"] <= 16/13 <= hydraulic["vertical_m_s"]["upper"]:
        raise ArithmeticError("independent series/parallel Darcy reference failed")
    if stability["mask"] != "VALID" or abs(stability["factor_of_safety"]-.95) > 2e-15:
        raise ArithmeticError("independent shallow-stability stress reference failed")
    return {"profile": profile, "hydraulics": hydraulic, "stability": stability,
            "status": "SYNTHETIC TEST ONLY; no property map, physical calibration or fertility model"}
