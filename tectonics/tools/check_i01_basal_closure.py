"""I01 basal closure (MC-04): a kinematic asthenosphere-inflow base for the regional rifting box, WORKING NON-CANON.

One selected law, atlas.basal-inflow-closure.v1, for the declared regional rifting experiment: a plane-strain box whose
fixed base lies in named asthenosphere below the retained 100 km lithosphere. The base normal velocity is prescribed
(uniform; reference rule u_in = (v_L + v_R) z_b / W, the ASPECT continental-extension cookbook's `v*2*d/w`) and its
tangential traction is zero. The sides prescribe outward normal velocity with zero tangential traction and move their
mesh only tangentially. The top is a free surface: zero traction, mesh normal velocity equal to the material normal
velocity. Temperature and composition are fixed only where material enters; outflow carries its actual state.

This tool implements only the boundary prescription, the moving-control-volume volume/mass/component/caloric/work
accounts on SUPPLIED interval fluxes, finite source/receiver proposals with atomic refusal, and the I05 open-base strip
adapter. It solves no Stokes, transport, melting or breakup problem: supplied or manufactured accounts are not a flow
solution. One exact Newtonian pure-shear field of a homogeneous box (an analytical solution checked in exact arithmetic,
not a numerical solve) supplies independent mechanical work terms for the ledger. No native code, retained tool or
receipt is imported or changed; three retained cases are read as JSON.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import platform
import time

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/"cases/i01_basal_closure_v1.json"
SCHEMA = "atlas.i01-basal-closure-case.v1"
EVIDENCE_SCHEMA = "atlas.i01-basal-closure-evidence.v1"
PASS = "PASS_BOUNDED_BASAL_CLOSURE_ONLY"
LAW = "atlas.basal-inflow-closure.v1"
PRESCRIPTION_ONLY = "BOUNDARY_PRESCRIPTION_ONLY"          # what to impose; nothing solved
PROPOSED = "PROPOSED_NOT_COMMITTED"                       # deltas for I02; nothing committed
SUPPLIED_ONLY = "SUPPLIED_ACCOUNTS_ONLY"                  # fluxes were supplied, not solved
ENDPOINT_CLOSES = "SUPPLIED_ENDPOINT_CLOSES"
NEW_FILES = ("tools/check_i01_basal_closure.py", "cases/i01_basal_closure_v1.json",
             "docs/I01_BASAL_CLOSURE.md", "tests/test_i01_basal_closure.py")
RETAINED = ("cases/i01_weakening_v1.json", "cases/i01_column_heat_v1.json", "cases/i01_finite_strain_v1.json")
ASPECT_YEAR_S = 31556952.0                                # ASPECT: a year is 60*60*24*365.2425 s
EPS = 2.0**-52

# Refusal codes. A refusal raises before any output exists; no caller input is modified.
INVALID = "REFUSED_INVALID_INPUT"
UNIT = "REFUSED_UNIT"
WINDOW = "REFUSED_OUTSIDE_WINDOW"
OVERDETERMINED = "REFUSED_OVERDETERMINED_COMPONENT"
UNDERDETERMINED = "REFUSED_UNDERDETERMINED_COMPONENT"
NOT_SELECTED = "REFUSED_NOT_SELECTED_LAW"
INCOMPATIBLE_FLUX = "REFUSED_INCOMPATIBLE_NORMAL_FLUX"
NULLSPACE = "REFUSED_PRESSURE_NULLSPACE"
LOCAL_FIELD = "REFUSED_LOCAL_FIELD_UNSPECIFIED"
NO_LAYER = "REFUSED_NO_ASTHENOSPHERE_LAYER"
POTENTIAL = "REFUSED_POTENTIAL_TEMPERATURE"
MELT = "REFUSED_MELT_BEARING_INFLOW"
NOT_ASTHENOSPHERE = "REFUSED_INCOMING_NOT_ASTHENOSPHERE"
SIDE_INFLOW = "REFUSED_SIDE_INFLOW"
DATUM = "REFUSED_DATUM_MISMATCH"
SOURCE_STATE = "REFUSED_SOURCE_STATE_MISMATCH"
EXHAUSTED = "REFUSED_SOURCE_EXHAUSTED"
OUTFLOW = "REFUSED_OUTFLOW_STATE"
VOLUME = "REFUSED_INCOMPATIBLE_VOLUME_BALANCE"
SURFACE = "REFUSED_UNOWNED_SURFACE_CROSSING"
LEDGER = "REFUSED_MECHANICAL_LEDGER"
THERMAL = "REFUSED_THERMAL_SOURCE"
CLOSED = "REFUSED_CLOSED_ROUTE"
ENDPOINT = "REFUSED_ENDPOINT_MISMATCH"
RETAINED_MISMATCH = "REFUSED_INCOMPATIBLE_RETAINED_CASE"
INVENTORY = "REFUSED_INVENTORY_VOLUME_MISMATCH"
THERMAL_BOUNDARY = "REFUSED_THERMAL_BOUNDARY_CONDITION"
FOREIGN = "REFUSED_FOREIGN_PROPOSAL"

# Frozen before any execution; cases/i01_basal_closure_v1.json must equal these dictionaries exactly.
POLICY = {
    "maximum_seconds": 10.0,
    "closure_relative": 1e-12,
    "oracle_relative": 1e-12,
    "temperature_window_k": [273.0, 1613.0],
    "stretch_window": [0.6, 1.4],
    "speed_limit_m_s": 1e-8,
    "scope": "one kinematic asthenosphere-inflow base for the declared regional rifting box; boundary prescription and "
             "moving-control-volume accounts on supplied or manufactured interval fluxes; finite proposals with atomic "
             "refusal; I05 open-base strip adapter; one exact analytical pure-shear control of the mechanical ledger; "
             "not a numerical Stokes, transport, melting or breakup solution",
}
PARAMETERS = {
    "configuration": {"width_m": 200000.0, "base_depth_m": 150000.0, "lithosphere_thickness_m": 100000.0,
                      "side_velocity_m_per_aspect_year": 0.0025, "aspect_year_s": 31556952.0,
                      "surface_temperature_k": 273.0, "base_temperature_k": 1613.0, "datum_k": 273.0,
                      "gravity_m_s2": 9.81},
    "cookbook": {"width_m": 200000.0, "depth_m": 100000.0, "side_velocity_m_per_aspect_year": 0.0025},
    "asthenosphere": {"name": "asthenosphere", "density_kg_m3": 3300.0, "heat_capacity_j_kg_k": 750.0,
                      "components": {"asthenosphere": 1.0}},
    "interval_aspect_years": 1000000.0,
    "exterior_source_mass_kg": 1e13,
    "dissipation_j": 1e15,
    "heat_fraction": 1.0,
    "datum_shifts_k": [0.0, 1000.0],
    "under_balance_factor": 0.8,
    "corner_offset_m": 500.0,
    "surface_slope": -0.01,
    "reversed": {"base_outward_velocity_m_per_aspect_year": 0.001, "outgoing_temperature_k": 1605.0,
                 "cohort_mean_temperature_k": 1600.0, "cohort_temperature_range_k": [1590.0, 1610.0]},
    "strip": {"reference_width_m": 100000.0, "stretch_start": 1.0, "stretch_extension": 1.2,
              "stretch_compression": 0.9},
    "pure_shear": {"viscosity_pa_s": 1e21},
}
UNITS = {
    "length": "m",
    "time": "s; ASPECT inputs in m/yr are converted with its 365.2425-day year",
    "velocity": "m/s; normal components positive outward",
    "volume": "m2 per metre of strike",
    "mass": "kg per metre of strike",
    "energy": "J per metre of strike",
    "temperature": "K, actual; potential temperature refused",
    "stress": "Pa; normal stress positive in tension",
    "specific_energy": "J/kg, Cp (T - T_ref) at the common datum",
}
WORK_OWNERSHIP = (
    {"term": "side normal reaction x prescribed side velocity", "owner": "exterior plates: prescribed reference now; "
     "D1 regional reaction in the force-driven coupling (I04/I09)", "booked": "mechanical ledger only"},
    {"term": "side and base tangential traction", "owner": "none: zero traction by the law", "booked": "no work"},
    {"term": "basal normal reaction x inflow, including the flow work P/rho of entering rock", "owner": "exterior "
     "asthenosphere account", "booked": "mechanical ledger only; never added to heat"},
    {"term": "free-surface traction", "owner": "none: traction-free; water or sediment loads are D5/I08 exchanges",
     "booked": "no work"},
    {"term": "D1 basal drag on the resolved footprint", "owner": "replaced by the resolved asthenosphere",
     "booked": "not applied a second time"},
    {"term": "gravity", "owner": "D1/D5 GPE ledger", "booked": "mechanical ledger"},
    {"term": "interior dissipation", "owner": "D2 rheology; D4 heat fraction (IN-05)", "booked": "mechanical sink; "
     "heat once as heat_fraction x dissipation"},
    {"term": "elastic storage", "owner": "open with MC-01 elastic memory", "booked": "not in this viscoplastic "
     "configuration"},
)


class Refusal(ValueError):
    """Atomic refusal: nothing is proposed or committed and no caller input is modified."""

    def __init__(self, code, message):
        super().__init__(code+": "+message)
        self.code = code


# ----------------------------------------------------------------------------- validated scalars

def require(condition, code, message):
    if not condition:
        raise Refusal(code, message)


def real(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refusal(INVALID, name+" must be a real number")
    value = float(value)
    require(math.isfinite(value), INVALID, name+" must be finite")
    return value


def positive(value, name):
    value = real(value, name)
    require(value > 0, INVALID, name+" must be positive")
    return value


def nonnegative(value, name):
    value = real(value, name)
    require(value >= 0, INVALID, name+" must be nonnegative")
    return value


def text(value, name):
    require(type(value) is str and value != "" and value.strip() == value, INVALID, name+" must be a non-empty name")
    return value


def record(value, name, required, optional=()):
    """An object with exactly the required fields plus declared optional ones; unknown fields are refused."""
    require(type(value) is dict, INVALID, name+" must be an object")
    missing = set(required)-set(value)
    unknown = set(value)-set(required)-set(optional)
    require(not missing, INVALID, f"{name} lacks {sorted(missing)}")
    require(not unknown, INVALID, f"{name} has unknown fields {sorted(unknown)}")
    return value


def temperature(value, name):
    value = real(value, name)
    low, high = POLICY["temperature_window_k"]
    require(low <= value <= high, WINDOW, f"{name} {value} K lies outside the admitted [{low}, {high}] K window")
    return value


def speed(value, name):
    value = real(value, name)
    require(abs(value) <= POLICY["speed_limit_m_s"], WINDOW, f"{name} exceeds {POLICY['speed_limit_m_s']} m/s: "
            "velocities are SI; convert m/yr explicitly")
    return value


def gross(*terms):
    """Scale of an account: the sum of absolute terms, never the (possibly zero) net."""
    return math.fsum(abs(t) for t in terms)


def closes(residual, scale):
    return abs(residual) <= POLICY["closure_relative"]*scale


def per_aspect_year(value_m_per_year, year_s):
    """An ASPECT m/yr input in m/s, using ASPECT's own year; any other year length is refused."""
    value = real(value_m_per_year, "velocity per ASPECT year")
    require(real(year_s, "ASPECT year") == ASPECT_YEAR_S, UNIT,
            "ASPECT velocities use its 365.2425-day year (31556952 s); a different year length is refused")
    return value/ASPECT_YEAR_S


# ----------------------------------------------------------------------------- materials and the incoming state

ROLES = ("asthenosphere", "mantle_lithosphere", "continental_crust", "oceanic_crust", "sediment")


@dataclass(frozen=True)
class Material:
    """Constant-density incompressible (Boussinesq reference) material with constant heat capacity."""
    name: str
    role: str
    density_kg_m3: float
    heat_capacity_j_kg_k: float
    components: tuple                   # ((component, mass fraction), ...), sorted; fractions sum to 1

    def specific_energy(self, temperature_k, datum_k):
        """Caloric energy per kg at the common datum, Cp (T - T_ref): the D4 heat content. No pressure term."""
        return self.heat_capacity_j_kg_k*(temperature_k-datum_k)


def material(name, value):
    text(name, "material name")
    record(value, "material "+name, ("role", "density_kg_m3", "heat_capacity_j_kg_k", "components"))
    require(value["role"] in ROLES, INVALID, f"material {name} role must be one of {ROLES}")
    parts = value["components"]
    require(type(parts) is dict and parts, INVALID, f"material {name} needs named components")
    fractions = tuple(sorted((text(k, "component"), positive(v, "component fraction")) for k, v in parts.items()))
    require(all(f <= 1 for _, f in fractions) and abs(math.fsum(f for _, f in fractions)-1) <= 4*EPS, INVALID,
            f"material {name} component fractions must sum to 1")
    return Material(name, value["role"], positive(value["density_kg_m3"], "density"),
                    positive(value["heat_capacity_j_kg_k"], "heat capacity"), fractions)


def materials_of(value):
    require(type(value) is dict and value, INVALID, "materials must be a non-empty object")
    return {name: material(name, item) for name, item in value.items()}


def incoming_state(value, materials, name):
    """Material entering through the base: named asthenosphere, solid, at its ACTUAL boundary temperature."""
    record(value, name, ("material", "temperature_k", "temperature_kind", "phase"))
    require(value["temperature_kind"] != "potential", POTENTIAL,
            "a potential temperature is not the boundary state: the selected Boussinesq energy law has no adiabatic "
            "heating, so no conversion is admitted; supply the actual boundary temperature")
    require(value["temperature_kind"] == "actual", INVALID, name+" temperature_kind must be 'actual'")
    require(value["phase"] == "solid", MELT, "melt-bearing inflow needs the MC-03 provider; only solid asthenosphere "
            "enters")
    mat = materials.get(value["material"]) if type(value["material"]) is str else None
    require(mat is not None, INVALID, name+" material is not declared")
    require(mat.role == "asthenosphere", NOT_ASTHENOSPHERE, "material entering through the base is asthenosphere, "
            f"never {mat.role} (no instant crust)")
    return mat, temperature(value["temperature_k"], name+" temperature")


# ----------------------------------------------------------------------------- I07 resolved boundary prescription

SELECTED_SEGMENTS = {"base": ("velocity", "traction", "fixed"), "left": ("velocity", "traction", "tangential"),
                     "right": ("velocity", "traction", "tangential"), "top": ("traction", "traction", "free_surface")}
CONDITIONS = ("velocity", "traction")
MESHES = ("fixed", "tangential", "free_surface", "material")


def component(value, name):
    """Exactly one of velocity or traction per component: the other is the solved reaction, never a second input."""
    require(type(value) is list and all(type(v) is str and v in CONDITIONS for v in value), INVALID,
            name+" must list 'velocity' or 'traction'")
    require(len(value) > 0, UNDERDETERMINED, name+" has neither a velocity nor a traction condition")
    require(len(value) == 1, OVERDETERMINED, name+" prescribes both velocity and traction; one must be the reaction")
    return value[0]


def flow_of(outward_velocity):
    return "inflow" if outward_velocity < 0 else ("outflow" if outward_velocity > 0 else "impermeable")


def thermal_condition(kind, mesh, flow):
    """The selected law's thermal condition on one segment in its actual flow regime.

    One table for resolved_prescription and propose_interval, so an account cannot carry a condition of its own. The
    free surface holds T_s, also under an owned surface exchange. Eulerian sides are insulating whatever crosses them.
    The base holds T_b where rock enters or nothing crosses, and has zero conductive flux where rock leaves. The
    material-following sides of the I05 strip carry no lateral conduction, because the strip supplies none.
    """
    if kind == "surface":
        return "dirichlet"
    if kind == "side":
        return "no_lateral_conduction" if mesh == "material" else "insulating"
    return "zero_conductive_flux" if flow == "outflow" else "dirichlet"


NO_CONDUCTION = ("insulating", "zero_conductive_flux", "no_lateral_conduction")


def resolved_prescription(config):
    """I07 boundary prescription for the selected box: what the resolved solver imposes and must return.

    A specification only: it solves no velocity, pressure or temperature field and books no account.
    """
    record(config, "configuration", ("law", "consumer", "width_m", "base_depth_m", "lithosphere_thickness_m",
                                     "segments", "side_outward_velocity_m_s", "basal_rule", "materials", "incoming",
                                     "surface_temperature_k"),
           ("basal_outward_velocity_m_s", "top_outward_velocity_m_s"))
    require(config["law"] == LAW, NOT_SELECTED, "only "+LAW+" is specified")
    consumer = config["consumer"]
    require(consumer in ("i07_resolved", "i05_accounts"), INVALID, "consumer must be i07_resolved or i05_accounts")
    width = positive(config["width_m"], "width")
    depth = positive(config["base_depth_m"], "base depth")
    lithosphere = positive(config["lithosphere_thickness_m"], "lithosphere thickness")
    if consumer == "i07_resolved":
        require(depth > lithosphere, NO_LAYER, "the separation experiment needs asthenosphere between the lithosphere "
                "base and the inflow base: ASPECT states its base at the lithosphere base cannot represent breakup")
    else:
        require(depth >= lithosphere, NO_LAYER, "the inflow base must lie at or below the lithosphere base")
    segments = config["segments"]
    require(type(segments) is dict and set(segments) == set(SELECTED_SEGMENTS), INVALID,
            "the selected box has exactly the segments base, left, right and top")
    kinds = {}
    for name in SELECTED_SEGMENTS:
        seg = record(segments[name], name, ("normal", "tangential", "mesh"))
        kinds[name] = (component(seg["normal"], name+" normal"), component(seg["tangential"], name+" tangential"),
                       seg["mesh"])
        require(seg["mesh"] in MESHES, INVALID, name+" mesh convention is unknown")
    sides = config["side_outward_velocity_m_s"]
    require(type(sides) is list and len(sides) == 2, INVALID, "two side outward velocities are required")
    v_left, v_right = (speed(v, "side outward velocity") for v in sides)
    require(v_left >= 0 and v_right >= 0, SIDE_INFLOW, "side inflow lies outside the selected rifting configuration")
    rule = config["basal_rule"]
    if rule == "total_flux":
        raise Refusal(LOCAL_FIELD, "a total basal flux does not define the local normal velocity; v1 admits only a "
                      "declared uniform distribution")
    if rule == "reference_constant_volume":
        require("basal_outward_velocity_m_s" not in config, INVALID, "the reference rule derives the basal velocity")
        u_base = speed(-(v_left+v_right)*depth/width, "reference basal velocity")
    elif rule == "declared_uniform":
        require("basal_outward_velocity_m_s" in config, INVALID, "declared_uniform needs basal_outward_velocity_m_s")
        u_base = speed(config["basal_outward_velocity_m_s"], "basal outward velocity")
    else:
        raise Refusal(INVALID, "basal_rule must be reference_constant_volume or declared_uniform")
    top_velocity = kinds["top"][0] == "velocity"
    require(top_velocity == ("top_outward_velocity_m_s" in config), INVALID,
            "top_outward_velocity_m_s is required exactly when the top normal velocity is prescribed")
    rates = {"left": v_left*depth, "right": v_right*depth, "base": u_base*width}
    if top_velocity:
        rates["top"] = speed(config["top_outward_velocity_m_s"], "top outward velocity")*width
    rates = {name: rate for name, rate in rates.items() if kinds[name][0] == "velocity"}
    if all(kind[0] == "velocity" for kind in kinds.values()):
        # No traction on any normal component: incompressibility needs zero net prescribed flux, and the constant
        # pressure mode is then undetermined. The selected law avoids both with its traction-free surface.
        net = math.fsum(rates.values())
        require(closes(net, gross(*rates.values())), INCOMPATIBLE_FLUX, f"prescribed normal fluxes sum to {net} m2/s; "
                "an incompressible box without a traction boundary has no solution")
        raise Refusal(NULLSPACE, "without a traction boundary the pressure is determined only up to a constant; the "
                      "selected law takes its datum from the free surface")
    for name, selected in SELECTED_SEGMENTS.items():
        require(kinds[name] == selected, NOT_SELECTED, f"{name} must be {selected} (normal, tangential, mesh) in {LAW}")
    materials = materials_of(config["materials"])
    mat, t_base = incoming_state(config["incoming"], materials, "incoming state")
    t_surface = temperature(config["surface_temperature_k"], "surface temperature")
    net = math.fsum(rates.values())
    base_flow = flow_of(u_base)
    base_thermal = thermal_condition("base", "fixed", base_flow)
    if base_flow == "outflow":
        base_temperature = {"type": base_thermal, "advected_state": "actual outgoing state, never reset"}
        base_composition = {"type": "natural", "advected_state": "actual outgoing composition and history"}
    else:
        base_temperature = {"type": base_thermal, "value_k": t_base,
                            "applies_to": "inflow and impermeable parts only (ASPECT option: no fixed temperature "
                                          "on outflow boundaries)"}
        base_composition = ({"type": "fixed_on_inflow", "material": mat.name, "raw_plastic_history": 0.0}
                            if base_flow == "inflow" else {"type": "natural", "advected_state": "none crosses"})
    def side(v):
        return {"normal": {"prescribed": "velocity", "outward_velocity_m_s": v,
                           "reaction": "normal traction (solver output)"},
                "tangential": {"prescribed": "traction", "traction_pa": 0.0, "solved": "tangential velocity"},
                "mesh": "tangential motion only (w.n = 0)", "flow": flow_of(v),
                "temperature": {"type": thermal_condition("side", "tangential", flow_of(v))},
                "composition": {"type": "natural", "advected_state": "actual outgoing state"}}

    return {
        "status": PRESCRIPTION_ONLY, "stokes_solution": False, "law": LAW, "consumer": consumer,
        "geometry": {"width_m": width, "base_depth_m": depth, "lithosphere_thickness_m": lithosphere,
                     "asthenosphere_layer_m": depth-lithosphere},
        "segments": {
            "base": {"normal": {"prescribed": "velocity", "outward_velocity_m_s": u_base,
                                "distribution": "uniform (declared)", "rule": rule,
                                "reaction": "normal traction (solver output)"},
                     "tangential": {"prescribed": "traction", "traction_pa": 0.0, "solved": "tangential velocity"},
                     "mesh": "fixed (w = 0)", "flow": base_flow, "temperature": base_temperature,
                     "composition": base_composition},
            "left": side(v_left), "right": side(v_right),
            "top": {"normal": {"prescribed": "traction", "traction_pa": 0.0, "solved": "normal velocity"},
                    "tangential": {"prescribed": "traction", "traction_pa": 0.0, "solved": "tangential velocity"},
                    "mesh": "free surface: w.n = u.n (normal projection); no surface diffusion in this law",
                    "flow": "impermeable material surface",
                    "temperature": {"type": thermal_condition("surface", "free_surface", "impermeable"),
                                    "value_k": t_surface},
                    "composition": {"type": "none", "advected_state": "none crosses"}},
        },
        "pressure": {"datum": "absolute: zero traction on the free surface", "normalisation": "none",
                     "nullspace": "none: the traction-free surface fixes the constant pressure mode",
                     "flux_compatibility": "not required: the free surface absorbs the net normal flux as "
                                           "domain-volume change"},
        "incoming": {"material": mat.name, "role": mat.role, "temperature_k": t_base, "temperature_kind": "actual",
                     "phase": "solid", "raw_plastic_history": 0.0},
        "net_prescribed_outflow_m2_s": net,
        "initial_domain_volume_rate_m2_s": -net,
        "work_ownership": [dict(item) for item in WORK_OWNERSHIP],
        "solver_outputs_required": [
            "normal traction on every velocity-prescribed normal component and the resulting boundary work",
            "tangential velocity on every traction-prescribed tangential component",
            "free-surface position and swept volume per interval",
            "per segment and interval: material volume crossing, with the actual outgoing temperature and cohort",
            "conductive heat through every segment, separately from advected heat",
            "interior dissipation and gravity work; domain volume at both ends",
        ],
    }


# ----------------------------------------------------------------------------- moving-control-volume accounts

KINDS = ("base", "side", "surface")
INTERIOR_FIELDS = ("radiogenic_j", "dissipation_j", "heat_fraction")
ACCOUNT_FIELDS = ("law", "parent", "interval_s", "datum_k", "materials", "domain", "sources", "receivers", "segments",
                  "streams", "conduction_in_j", "interior")


def volume_account(volume_start, volume_end, swept, inflow, outflow):
    """Moving control volume of incompressible material, per metre of strike.

    dV equals the summed swept volume of the moving boundary (integral w.n dl dt) and, independently, the net material
    inflow across it (minus integral (u - w).n dl dt). Both are checked; a mismatch is refused, never repaired by
    adjusting a flux or a surface position. Inflow equals outflow only when dV is zero.
    """
    v0 = positive(volume_start, "start domain volume")
    v1 = positive(volume_end, "end domain volume")
    swept = [real(s, "swept volume") for s in swept]
    inflow = [positive(q, "inflow volume") for q in inflow]
    outflow = [positive(q, "outflow volume") for q in outflow]
    change = v1-v0
    mesh = math.fsum(swept)
    material = math.fsum(inflow+[-q for q in outflow])
    scale = gross(v0, v1, *swept, *inflow, *outflow)
    require(closes(change-mesh, scale), VOLUME, f"domain volume change {change} m2 differs from the boundary motion "
            f"{mesh} m2")
    require(closes(change-material, scale), VOLUME, f"domain volume change {change} m2 differs from the net material "
            f"inflow {material} m2; no flux or surface position is corrected")
    return {"start_m2": v0, "end_m2": v1, "change_m2": change, "swept_m2": mesh, "inflow_m2": math.fsum(inflow),
            "outflow_m2": math.fsum(outflow), "net_material_inflow_m2": material,
            "inflow_equals_outflow": closes(material, scale), "scale_m2": scale}


def cohort(name, value, materials, datum):
    text(name, "cohort name")
    record(value, "cohort "+name, ("material", "mass_kg", "energy_j", "temperature_range_k", "datum_k"))
    require(real(value["datum_k"], "cohort datum") == datum, DATUM, f"cohort {name} energy uses another datum")
    mat = materials.get(value["material"]) if type(value["material"]) is str else None
    require(mat is not None, INVALID, f"cohort {name} material is not declared")
    mass = nonnegative(value["mass_kg"], "cohort mass")
    energy = real(value["energy_j"], "cohort energy")
    span = value["temperature_range_k"]
    require(type(span) is list and len(span) == 2, INVALID, f"cohort {name} needs [lowest, highest] temperature")
    low, high = (temperature(t, f"cohort {name} temperature bound") for t in span)
    require(low <= high, INVALID, f"cohort {name} temperature range is reversed")
    bounds = (mass*mat.specific_energy(low, datum), mass*mat.specific_energy(high, datum))
    tolerance = POLICY["closure_relative"]*gross(energy, *bounds)
    require(bounds[0]-tolerance <= energy <= bounds[1]+tolerance, INVALID, f"cohort {name} energy is not a mean "
            "temperature inside its declared range")
    return mat, mass, energy, (low, high)


def source(name, value, materials, datum):
    """A finite named exterior asthenosphere account at one uniform actual state."""
    text(name, "source name")
    record(value, "source "+name, ("material", "mass_kg", "energy_j", "temperature_k", "temperature_kind", "phase",
                                    "datum_k"))
    require(real(value["datum_k"], "source datum") == datum, DATUM, f"source {name} energy uses another datum")
    mat, t = incoming_state({key: value[key] for key in ("material", "temperature_k", "temperature_kind", "phase")},
                            materials, "source "+name)
    mass = nonnegative(value["mass_kg"], "source mass")
    energy = real(value["energy_j"], "source energy")
    expected = mass*mat.specific_energy(t, datum)
    require(closes(energy-expected, gross(energy, expected)), SOURCE_STATE, f"source {name} energy is not its mass at "
            "the declared actual state and datum (caloric Cp (T - T_ref); no pressure term)")
    return mat, t, mass, energy


def segment(name, value):
    text(name, "segment name")
    record(value, "segment "+name, ("kind", "mesh", "swept_volume_m2"), ("owner",))
    kind, mesh = value["kind"], value["mesh"]
    require(kind in KINDS and mesh in MESHES, INVALID, f"segment {name} kind or mesh is unknown")
    allowed = {"base": ("fixed",), "side": ("fixed", "tangential", "material"), "surface": ("free_surface",)}[kind]
    require(mesh in allowed, NOT_SELECTED, f"a {kind} segment of {LAW} moves as {allowed}, not {mesh}")
    swept = real(value["swept_volume_m2"], "swept volume")
    require(mesh in ("free_surface", "material") or swept == 0, VOLUME, f"segment {name} does not move normal to "
            "itself, so it sweeps no volume")
    owner = value.get("owner")
    require(owner is None or (kind == "surface" and text(owner, "surface-exchange owner") == owner), INVALID,
            "only a free-surface segment may name a surface-exchange owner")
    return kind, mesh, swept, owner


def interior(value):
    require(type(value) is dict, INVALID, "interior must be an object")
    unknown = set(value)-set(INTERIOR_FIELDS)-{"gravity_work_j"}
    require(not unknown, THERMAL, f"{sorted(unknown)} not admitted: heat comes only from radiogenic sources and the "
            "declared fraction of interior dissipation; boundary work and latent heat are not heat sources here")
    require(set(INTERIOR_FIELDS) <= set(value), INVALID, f"interior needs {INTERIOR_FIELDS}")
    radiogenic = nonnegative(value["radiogenic_j"], "radiogenic heat")
    dissipation = nonnegative(value["dissipation_j"], "interior dissipation")
    fraction = real(value["heat_fraction"], "heat fraction")
    require(0 <= fraction <= 1, INVALID, "heat fraction must lie in [0, 1]")
    gravity = real(value["gravity_work_j"], "gravity work") if "gravity_work_j" in value else None
    return radiogenic, dissipation, fraction, gravity


def stream_of(index, item, segments, sources, cohorts, receivers, direction_of):
    label = f"stream {index}"
    require(type(item) is dict and item.get("direction") in ("in", "out"), INVALID, label+" direction must be in or out")
    if item["direction"] == "in":
        record(item, label, ("segment", "direction", "volume_m2", "source"))
    else:
        require("temperature_k" in item, OUTFLOW, label+" must state the actual outgoing temperature; there is no "
                "default boundary value")
        record(item, label, ("segment", "direction", "volume_m2", "cohort", "temperature_k", "receiver"))
    name = item["segment"]
    require(type(name) is str and name in segments, INVALID, label+" names an undeclared segment")
    kind, mesh, _, owner = segments[name]
    require(direction_of.setdefault(name, item["direction"]) == item["direction"], INVALID, f"segment {name} carries "
            "inflow and outflow in one record; split it where the normal flux changes sign")
    volume = positive(item["volume_m2"], label+" volume")
    if kind == "surface":
        require(owner is not None, SURFACE, f"material crosses the free surface {name} without a named owner; a free "
                "surface is a material surface unless a surface-process exchange owns the crossing")
        require(item["direction"] == "out", SURFACE, "v1 admits only owned outgoing surface exchange")
    if kind == "side":
        require(mesh != "material", VOLUME, f"no material crosses the material-following side {name}")
        require(item["direction"] == "out", SIDE_INFLOW, "side inflow lies outside the selected rifting configuration")
    if item["direction"] == "in":
        require(kind == "base", SURFACE, "material enters only through the base")
        require(type(item["source"]) is str and item["source"] in sources, INVALID, label+" names an undeclared source")
        mat, t, *_ = sources[item["source"]]
        return "in", (name, item["source"], mat, t, volume)
    require(type(item["cohort"]) is str and item["cohort"] in cohorts, OUTFLOW, label+" debits an undeclared cohort")
    require(type(item["receiver"]) is str and item["receiver"] in receivers, OUTFLOW,
            label+" credits an undeclared receiver")
    mat, _, _, (low, high) = cohorts[item["cohort"]]
    t = temperature(item["temperature_k"], label+" temperature")
    require(low <= t <= high, OUTFLOW, f"{label} leaves at {t} K, outside cohort {item['cohort']} range [{low}, "
            f"{high}] K: outflow carries the actual state, never a reset boundary value")
    return "out", (name, item["cohort"], item["receiver"], mat, t, volume)


FLOW_OF_DIRECTION = {None: "impermeable", "in": "inflow", "out": "outflow"}


def propose_interval(account):
    """Book one interval's boundary transfers from SUPPLIED fluxes; return proposed deltas for I02 to commit once.

    Everything is validated before any result exists. The caller's account is never modified; nothing is committed.
    Under the constant reference densities the cohorts must fill the domain volume at both ends (never rescaled), and
    each segment's conductive heat must obey the law's thermal condition for its kind and actual flow regime.
    """
    record(account, "account", ACCOUNT_FIELDS, ("boundary_work_in_j",))
    require(account["law"] == LAW, NOT_SELECTED, "only "+LAW+" is specified")
    parent = text(account["parent"], "parent")
    span = account["interval_s"]
    require(type(span) is list and len(span) == 2, INVALID, "interval_s must be [start, end]")
    t0, t1 = (real(t, "interval bound") for t in span)
    require(t1 > t0, INVALID, "the interval must have positive duration")
    datum = nonnegative(account["datum_k"], "datum")
    materials = materials_of(account["materials"])
    domain = record(account["domain"], "domain", ("volume_start_m2", "volume_end_m2", "cohorts"))
    require(type(domain["cohorts"]) is dict, INVALID, "domain cohorts must be an object")
    cohorts = {name: cohort(name, item, materials, datum) for name, item in domain["cohorts"].items()}
    v0 = positive(domain["volume_start_m2"], "start domain volume")
    held = [mass/mat.density_kg_m3 for mat, mass, _, _ in cohorts.values()]
    inventory_start = math.fsum(held)
    require(closes(inventory_start-v0, gross(v0, *held)), INVENTORY, f"the start cohorts occupy {inventory_start} m2 at "
            f"their reference densities, but the domain volume is {v0} m2; no mass or volume is rescaled")
    require(type(account["sources"]) is dict, INVALID, "sources must be an object")
    sources = {name: source(name, item, materials, datum) for name, item in account["sources"].items()}
    receivers = account["receivers"]
    require(type(receivers) is list and all(type(r) is str and r for r in receivers)
            and len(set(receivers)) == len(receivers), INVALID, "receivers must be distinct names")
    require(not set(receivers) & set(sources), OUTFLOW, "outflow cannot return to a finite source: no mixing law is "
            "admitted, so outgoing material goes to a separate named receiver")
    require(type(account["segments"]) is dict and account["segments"], INVALID, "segments must be a non-empty object")
    segments = {name: segment(name, item) for name, item in account["segments"].items()}
    kinds = [value[0] for value in segments.values()]
    require("base" in kinds and "surface" in kinds, NOT_SELECTED, "the domain needs a base and a free surface")
    require(type(account["streams"]) is list, INVALID, "streams must be a list")
    direction_of, inflows, outflows = {}, [], []
    for index, item in enumerate(account["streams"]):
        way, row = stream_of(index, item, segments, sources, cohorts, receivers, direction_of)
        (inflows if way == "in" else outflows).append(row)
    conduction = account["conduction_in_j"]
    require(type(conduction) is dict and set(conduction) == set(segments), INVALID, "conduction_in_j needs one explicit "
            "term per segment, positive into the domain (zero where insulating)")
    conduction = {name: real(value, "conductive heat") for name, value in conduction.items()}
    conditions = {name: thermal_condition(kind, mesh, FLOW_OF_DIRECTION[direction_of.get(name)])
                  for name, (kind, mesh, _, _) in segments.items()}
    for name, condition in conditions.items():
        require(condition not in NO_CONDUCTION or conduction[name] == 0, THERMAL_BOUNDARY, f"segment {name} is "
                f"{condition} under {LAW} in its actual flow regime, so its conductive heat must be zero, not "
                f"{conduction[name]} J/m")
    radiogenic, dissipation, fraction, gravity = interior(account["interior"])
    volume = volume_account(v0, domain["volume_end_m2"], [s[2] for s in segments.values()],
                            [row[4] for row in inflows], [row[5] for row in outflows])

    new_cohorts, by_source, by_cohort, by_receiver, component_terms = {}, {}, {}, {}, {}
    energy_in, energy_out = [], []
    for seg, src, mat, t, vol in inflows:
        mass = mat.density_kg_m3*vol
        energy = mass*mat.specific_energy(t, datum)
        key = f"inflow:{seg}:{src}:{t0!r}:{t1!r}"
        require(key not in new_cohorts, INVALID, "one inflow stream per segment and source per interval")
        new_cohorts[key] = {"material": mat.name, "role": mat.role, "mass_kg": mass, "energy_j": energy,
                            "temperature_k": t, "raw_plastic_history": 0.0, "entry_interval_s": [t0, t1],
                            "source": src, "segment": seg, "volume_m2": vol}
        by_source.setdefault(src, []).append((mass, energy))
        for comp, frac in mat.components:
            component_terms.setdefault(comp, []).append(mass*frac)
        energy_in.append(energy)
    for seg, coh, rec, mat, t, vol in outflows:
        mass = mat.density_kg_m3*vol
        energy = mass*mat.specific_energy(t, datum)
        by_cohort.setdefault(coh, []).append((mass, energy))
        by_receiver.setdefault(rec, []).append((mass, energy, mat, seg, coh, t))
        for comp, frac in mat.components:
            component_terms.setdefault(comp, []).append(-mass*frac)
        energy_out.append(energy)

    source_deltas = {}
    for src, rows in by_source.items():
        mat, _, available, stored = sources[src]
        demand = math.fsum(m for m, _ in rows)                 # joint demand: no first-come allocation
        require(demand <= available, EXHAUSTED, f"source {src} holds {available} kg but the interval demands {demand} "
                "kg; exhaustion refuses the whole proposal and never clips the stock")
        taken = math.fsum(e for _, e in rows)
        source_deltas[src] = {"mass_kg": -demand, "energy_j": -taken,
                              "components_kg": {c: -demand*f for c, f in mat.components},
                              "remaining_mass_kg": available-demand, "remaining_energy_j": math.fsum((stored, -taken))}
    cohort_deltas, remaining = {}, {name: mass for name, (_, mass, _, _) in cohorts.items()}
    for coh, rows in by_cohort.items():
        mat, available, stored, (low, high) = cohorts[coh]
        mass = math.fsum(m for m, _ in rows)
        require(mass <= available, OUTFLOW, f"outflow of {mass} kg exceeds cohort {coh} ({available} kg)")
        taken = math.fsum(e for _, e in rows)
        rest_mass, rest_energy = available-mass, math.fsum((stored, -taken))
        bounds = (rest_mass*mat.specific_energy(low, datum), rest_mass*mat.specific_energy(high, datum))
        tolerance = POLICY["closure_relative"]*gross(stored, taken, *bounds)
        require(bounds[0]-tolerance <= rest_energy <= bounds[1]+tolerance, OUTFLOW, f"cohort {coh} cannot supply these "
                "outgoing states: its remaining energy lies outside its declared temperature range")
        cohort_deltas[coh] = {"mass_kg": -mass, "energy_advected_j": -taken}
        remaining[coh] = rest_mass
    # Implied by the start inventory and the two volume checks (each transfer's mass is its volume times its own
    # density), but recomputed from the booked masses: this is the end state I02 would commit.
    filled = ([remaining[name]/cohorts[name][0].density_kg_m3 for name in cohorts]
              + [row["mass_kg"]/materials[row["material"]].density_kg_m3 for row in new_cohorts.values()])
    inventory_end = math.fsum(filled)
    require(closes(inventory_end-volume["end_m2"], gross(volume["end_m2"], *filled)), INVENTORY, f"the end cohorts "
            f"occupy {inventory_end} m2 at their reference densities, but the end domain volume is {volume['end_m2']} m2")
    receiver_deltas = {}
    for rec, rows in by_receiver.items():
        parts = {}
        for m, _, mat, *_ in rows:
            for comp, frac in mat.components:
                parts.setdefault(comp, []).append(m*frac)
        receiver_deltas[rec] = {"mass_kg": math.fsum(r[0] for r in rows), "energy_j": math.fsum(r[1] for r in rows),
                                "components_kg": {c: math.fsum(v) for c, v in sorted(parts.items())},
                                "parts": [{"segment": s, "cohort": c, "temperature_k": t, "mass_kg": m, "energy_j": e}
                                          for m, e, _, s, c, t in rows]}

    work = account.get("boundary_work_in_j")
    if work is None:
        require(gravity is None, LEDGER, "gravity work without boundary work does not form a mechanical ledger")
        mechanical = {"status": "NOT_SUPPLIED", "dissipation_j": dissipation}
    else:
        require(type(work) is dict and set(work) == set(segments), INVALID, "boundary_work_in_j needs one term per "
                "segment, positive into the domain")
        work = {name: real(value, "boundary work") for name, value in work.items()}
        for name, (kind, *_) in segments.items():
            require(kind != "surface" or work[name] == 0, LEDGER, f"the traction-free surface {name} does no work")
        require(gravity is not None, LEDGER, "the mechanical ledger needs the interior gravity work")
        residual = math.fsum(list(work.values())+[gravity, -dissipation])
        require(closes(residual, gross(*work.values(), gravity, dissipation)), LEDGER, f"boundary + gravity work - "
                f"dissipation = {residual} J/m: the Stokes ledger (no inertia, no elastic storage) does not close")
        mechanical = {"status": "CLOSED", "boundary_work_in_j": work, "gravity_work_j": gravity,
                      "dissipation_j": dissipation, "residual_j": residual,
                      "note": "boundary work stays in this ledger; heat receives only heat_fraction x dissipation"}

    dissipation_heat = fraction*dissipation
    change = math.fsum(energy_in+[-e for e in energy_out]+list(conduction.values())+[radiogenic, dissipation_heat])
    return {
        "status": PROPOSED, "evidence": SUPPLIED_ONLY, "stokes_solution": False, "law": LAW, "parent": parent,
        "interval_s": [t0, t1], "datum_k": datum,
        "volume": dict(volume, inventory_start_m2=inventory_start, inventory_end_m2=inventory_end),
        "start_cohorts": {name: {"material": mat.name, "mass_kg": mass, "energy_j": energy}
                          for name, (mat, mass, energy, _) in cohorts.items()},
        "sources": source_deltas, "receivers": receiver_deltas,
        "domain": {"cohorts": cohort_deltas, "new_cohorts": new_cohorts,
                   "components_kg": {c: math.fsum(v) for c, v in sorted(component_terms.items())},
                   "mass_kg": math.fsum([r["mass_kg"] for r in new_cohorts.values()]
                                        + [d["mass_kg"] for d in cohort_deltas.values()]),
                   "energy_j": change},
        "thermal": {"boundary_conditions": conditions,
                    "advected_in_j": math.fsum(energy_in), "advected_out_j": math.fsum(energy_out),
                    "conduction_in_j": conduction, "radiogenic_j": radiogenic, "dissipation_heat_j": dissipation_heat,
                    "change_j": change},
        "mechanical": mechanical,
    }


def flow_work(normal_stress_pa, material_flux_m2):
    """Boundary work into the domain, sigma_nn q, for a uniform normal stress (tension positive), zero tangential
    traction and a fixed segment; q = integral (u - w).n dl dt is positive outward. Lithostatic inflow gives P V_in."""
    return real(normal_stress_pa, "normal stress")*real(material_flux_m2, "material flux")


def specific_enthalpy(mat, temperature_k, pressure_pa, datum_k):
    """Diagnostic only: incompressible h = Cp (T - T_ref) + P/rho. The thermal account advects Cp (T - T_ref); the
    P/rho part is flow work that the boundary traction already carries in the mechanical ledger."""
    return mat.specific_energy(temperature_k, datum_k)+real(pressure_pa, "pressure")/mat.density_kg_m3


def diagnose_endpoint(account, proposal, end_mass_kg, end_energy_j, end_volume_m2):
    """Compare a SUPPLIED end state (for example a future resolved solve) with the booked boundary accounts.

    The proposal must be the one this account books: it is recomputed from the account (a small pure function) and
    compared in full, so a foreign parent or interval, an account edited after booking or edited deltas are refused.
    No status, law or claimed digest authenticates contents. The supplied end volume must equal the booked end volume,
    and the supplied cohorts must fill it at their reference densities. Per-cohort mass must equal start plus booked
    transfers; conduction moves heat between cohorts, so only the total caloric energy is compared. Closing is
    consistency of supplied data, not a flow solution.
    """
    booked = propose_interval(account)
    require(proposal == booked, FOREIGN, "the proposal is not the one this account books: its parent, interval, inputs "
            "or deltas differ from a proposal recomputed from the same account")
    materials = materials_of(account["materials"])
    start = booked["start_cohorts"]
    expected, density = {}, {}
    for name, item in start.items():
        expected[name], density[name] = item["mass_kg"], materials[item["material"]].density_kg_m3
    for name, delta in booked["domain"]["cohorts"].items():
        expected[name] = math.fsum((expected[name], delta["mass_kg"]))
    for name, item in booked["domain"]["new_cohorts"].items():
        expected[name], density[name] = item["mass_kg"], materials[item["material"]].density_kg_m3
    require(type(end_mass_kg) is dict and set(end_mass_kg) == set(expected), ENDPOINT, "the supplied end state must "
            "list every start and new cohort")
    supplied_mass, residuals = {}, {}
    for name, value in expected.items():
        supplied = supplied_mass[name] = nonnegative(end_mass_kg[name], "end mass")
        residuals[name] = supplied-value
        require(closes(residuals[name], gross(supplied, value, start.get(name, {}).get("mass_kg", 0.0))), ENDPOINT,
                f"cohort {name} end mass differs from start plus booked transfers by {residuals[name]} kg")
    volume = positive(end_volume_m2, "end domain volume")
    booked_volume = booked["volume"]["end_m2"]
    require(closes(volume-booked_volume, gross(volume, booked_volume)), ENDPOINT, f"the supplied end domain volume "
            f"{volume} m2 differs from the booked end volume {booked_volume} m2")
    filled = [supplied_mass[name]/density[name] for name in expected]
    inventory = math.fsum(filled)
    require(closes(inventory-volume, gross(volume, *filled)), ENDPOINT, f"the supplied end cohorts occupy {inventory} "
            f"m2 at their reference densities, not the end domain volume {volume} m2")
    thermal = booked["thermal"]
    start_energy = math.fsum(item["energy_j"] for item in start.values())
    target = math.fsum((start_energy, booked["domain"]["energy_j"]))
    supplied = real(end_energy_j, "end energy")
    scale = gross(start_energy, supplied, thermal["advected_in_j"], thermal["advected_out_j"],
                  *thermal["conduction_in_j"].values(), thermal["radiogenic_j"], thermal["dissipation_heat_j"])
    require(closes(supplied-target, scale), ENDPOINT, f"end caloric energy differs from the booked balance by "
            f"{supplied-target} J/m")
    return {"status": ENDPOINT_CLOSES, "stokes_solution": False, "mass_residual_kg": residuals,
            "volume_residual_m2": volume-booked_volume, "inventory_residual_m2": inventory-volume,
            "energy_residual_j": supplied-target}


# ----------------------------------------------------------------------------- I05 open-domain strip interface

def strip_open_base(*, route, reference_width_m, base_depth_m, lithosphere_thickness_m, stretch_start, stretch_end):
    """I05 open-base column: the accepted affine strip's pure shear about the stationary surface, over the full depth to
    a fixed base z_b >= h0, with material-following sides. The base is the only permeable segment: its volume is
    w0 z_b |lam1 - lam0| (inflow while stretching, outflow while shortening) and each side sweeps z_b w0 (lam1 - lam0)/2.
    The lithosphere base h0/lam must stay at or above z_b at both endpoints: below it, lithosphere would have to leave
    through the base, a route this adapter does not provide, so it is refused and never exported as asthenosphere.
    The closed strip keeps its own inventory and fixed material-base temperature; this adapter never changes them.
    """
    require(route == "open_base", CLOSED, "the closed strip admits no basal transfer; its inventory and fixed "
            "material-base temperature stay unchanged")
    w0 = positive(reference_width_m, "reference width")
    depth = positive(base_depth_m, "base depth")
    h0 = positive(lithosphere_thickness_m, "lithosphere thickness")
    require(depth >= h0, NO_LAYER, "the open base must lie at or below the lithosphere base")
    low, high = POLICY["stretch_window"]
    lam0, lam1 = real(stretch_start, "start stretch"), real(stretch_end, "end stretch")
    require(low <= lam0 <= high and low <= lam1 <= high, WINDOW, f"stretch outside the accepted [{low}, {high}] window")
    for when, lam in (("start", lam0), ("end", lam1)):
        require(h0/lam <= depth, NO_LAYER, f"at the {when} stretch {lam} the lithosphere base lies at {h0/lam} m, below "
                f"the fixed base at {depth} m: lithosphere would have to leave through the base, a route this adapter "
                "does not provide; it is never exported as asthenosphere")
    change = lam1-lam0
    half = depth*w0*change/2
    placement = {"lithosphere_base_depth_m": h0/lam1, "width_m": w0*lam1}
    if change > 0:
        placement["inflow_depth_range_m"] = [depth*lam0/lam1, depth]
    return {"law": LAW, "route": "open_base", "closed_route": "unchanged",
            "segments": {"base": {"kind": "base", "mesh": "fixed", "swept_volume_m2": 0.0},
                         "left": {"kind": "side", "mesh": "material", "swept_volume_m2": half},
                         "right": {"kind": "side", "mesh": "material", "swept_volume_m2": half},
                         "surface": {"kind": "surface", "mesh": "free_surface", "swept_volume_m2": 0.0}},
            "volume_start_m2": w0*lam0*depth, "volume_end_m2": w0*lam1*depth,
            "base_flux": {"direction": "in" if change > 0 else ("out" if change < 0 else None),
                          "volume_m2": w0*depth*abs(change)},
            "placement": placement}


# ----------------------------------------------------------------------------- geometry oracles

@dataclass(frozen=True)
class Segment:
    """A straight boundary segment traversed counter-clockwise around the domain; outward normal (dy, -dx)/L."""
    x0: float
    y0: float
    x1: float
    y1: float

    def crossing_rate(self, material_velocity, mesh_velocity):
        """integral (u - w).n dl for uniform u and w [m2/s, positive outward]; exact for a straight segment."""
        (ux, uy), (wx, wy) = material_velocity, mesh_velocity
        return (ux-wx)*(self.y1-self.y0)-(uy-wy)*(self.x1-self.x0)

    def normal_projection(self, material_velocity):
        """Mesh velocity (u.n) n: the segment follows only the material normal velocity (ASPECT 'normal')."""
        dx, dy = self.x1-self.x0, self.y1-self.y0
        un = material_velocity[0]*dy-material_velocity[1]*dx                # (u.n) L
        return (un*dy/(dx*dx+dy*dy), -un*dx/(dx*dx+dy*dy))


def polygon_area(points):
    """Shoelace area of a simple counter-clockwise polygon: an independent geometric oracle for domain volume."""
    return math.fsum(x0*y1-x1*y0 for (x0, y0), (x1, y1) in zip(points, points[1:]+points[:1]))/2


# ----------------------------------------------------------------------------- independent mechanical oracle

def central(f, x, y, h):
    """Exact central differences (df/dx, df/dy) of a field of degree <= 2 in each variable, in Fraction arithmetic."""
    return ((f(x+h, y)-f(x-h, y))/(2*h), (f(x, y+h)-f(x, y-h))/(2*h))


def simpson(f, lo, hi):
    """Simpson's rule: exact for polynomials of degree <= 3, so exact in Fraction arithmetic for these integrands."""
    return (hi-lo)/6*(f(lo)+4*f((lo+hi)/2)+f(hi))


@dataclass(frozen=True)
class PureShear:
    """Exact Newtonian pure shear in the box x in [-W/2, W/2], y in [0, H] (y up from the base), in exact Fractions.

    Only the velocity u = (a x, a (H - y)) and the stated pressure p = rho g (H - y) - 2 eta a are written down; the
    strain rate, the stress sigma = -p I + 2 eta D(u) and the momentum residual are derived from them. Constant
    viscosity eta and density rho, gravity (0, -g). A homogeneous analytical control for the mechanical ledger: not a
    numerical Stokes solve and not the layered column.
    """
    a: Fraction
    eta: Fraction
    rho: Fraction
    g: Fraction
    width: Fraction
    height: Fraction

    def velocity(self, x, y):
        return (self.a*x, self.a*(self.height-y))

    def pressure(self, x, y):
        return self.rho*self.g*(self.height-y)-2*self.eta*self.a

    def strain_rate(self, x, y):
        """(D_xx, D_yy, D_xy), the symmetric velocity gradient, by exact central differences of the linear velocity."""
        h = self.height/4
        (dux_dx, dux_dy), (duy_dx, duy_dy) = [central(lambda p, q, i=i: self.velocity(p, q)[i], x, y, h)
                                              for i in (0, 1)]
        return (dux_dx, duy_dy, (dux_dy+duy_dx)/2)

    def stress(self, x, y):
        """Cauchy stress (sigma_xx, sigma_yy, sigma_xy), tension positive, from the Newtonian law."""
        p = self.pressure(x, y)
        dxx, dyy, dxy = self.strain_rate(x, y)
        return (-p+2*self.eta*dxx, -p+2*self.eta*dyy, 2*self.eta*dxy)

    def lithostatic_stress(self, x, y):
        """Only the isotropic part -rho g (H - y) I: used to build the omitted-viscous-traction error, never booked."""
        s = -self.rho*self.g*(self.height-y)
        return (s, s, Fraction(0))

    def momentum_residual(self, x, y):
        """div sigma + rho (0, -g) by exact central differences of the affine stress: (0, 0) in Stokes equilibrium."""
        h = self.height/4
        (dxx_dx, _), (_, dyy_dy), (dxy_dx, dxy_dy) = [central(lambda p, q, i=i: self.stress(p, q)[i], x, y, h)
                                                      for i in range(3)]
        return (dxx_dx+dxy_dy, dxy_dx+dyy_dy-self.rho*self.g)

    def corners(self):
        """Counter-clockwise from the left end of the base; consecutive pairs are the base, right side, top, left side."""
        half = self.width/2
        return ((-half, Fraction(0)), (half, Fraction(0)), (half, self.height), (-half, self.height))


def traction_power(stress, velocity, start, end):
    """Power into the domain through a straight counter-clockwise segment: integral (sigma n).u dl.

    With s in [0, 1] along the segment, n dl = (dy, -dx) ds. The integrand is at most quadratic in s, so Simpson's rule
    in exact arithmetic gives the exact integral.
    """
    (x0, y0), (x1, y1) = start, end
    nx, ny = y1-y0, x0-x1

    def integrand(s):
        x, y = x0+s*(x1-x0), y0+s*(y1-y0)
        sxx, syy, sxy = stress(x, y)
        ux, uy = velocity(x, y)
        return (sxx*nx+sxy*ny)*ux+(sxy*nx+syy*ny)*uy
    return simpson(integrand, Fraction(0), Fraction(1))


def pure_shear_powers(field):
    """Independent powers per metre of strike [W/m] of the exact pure-shear box, each from its own physics.

    Boundary power: traction times velocity on each segment. Gravity power: rho g.u over the area. Dissipation:
    sigma : D over the area. Each is integrated exactly on its own (tensor Simpson over the box); none is set to close
    a ledger.
    """
    corners = field.corners()
    powers = {name: traction_power(field.stress, field.velocity, corners[i], corners[(i+1) % 4])
              for i, name in enumerate(("base", "right", "top", "left"))}
    half = field.width/2

    def over_box(f):
        return simpson(lambda x: simpson(lambda y: f(x, y), Fraction(0), field.height), -half, half)

    def stress_power(x, y):
        (sxx, syy, sxy), (dxx, dyy, dxy) = field.stress(x, y), field.strain_rate(x, y)
        return sxx*dxx+syy*dyy+2*sxy*dxy

    powers["gravity"] = over_box(lambda x, y: -field.rho*field.g*field.velocity(x, y)[1])
    powers["dissipation"] = over_box(stress_power)
    return powers


# ----------------------------------------------------------------------------- case and retained inputs

CASE_FIELDS = {"schema", "status", "task", "kind", "contract_document", "refines", "decision", "interfaces",
               "work_ownership", "units", "control_policy", "control_parameters", "parameter_provenance", "blocked",
               "acceptance_claim"}


def validate_parameters(par, pol):
    """Structural sanity of the frozen inputs; exact equality with the executable is checked by validate_case."""
    require(type(par) is dict and type(pol) is dict, INVALID, "parameters and policy must be objects")
    require(0 < real(pol["maximum_seconds"], "maximum seconds") <= 10, INVALID, "budget must lie in (0, 10] s")
    for key in ("closure_relative", "oracle_relative"):
        require(0 < real(pol[key], key) <= 1e-9, INVALID, key+" must be a round-off tolerance in (0, 1e-9]")
    for key in ("temperature_window_k", "stretch_window"):
        pair = pol[key]
        require(type(pair) is list and len(pair) == 2 and 0 < real(pair[0], key) < real(pair[1], key), INVALID,
                key+" must be an increasing positive pair")
    positive(pol["speed_limit_m_s"], "speed limit")
    cfg = par["configuration"]
    for key in ("width_m", "base_depth_m", "lithosphere_thickness_m", "gravity_m_s2"):
        positive(cfg[key], key)
    require(cfg["base_depth_m"] > cfg["lithosphere_thickness_m"], NO_LAYER, "the selected base lies in asthenosphere "
            "below the lithosphere")
    speed(per_aspect_year(cfg["side_velocity_m_per_aspect_year"], cfg["aspect_year_s"]), "side velocity")
    for key in ("surface_temperature_k", "base_temperature_k"):
        temperature(cfg[key], key)
    nonnegative(cfg["datum_k"], "datum")
    book = par["cookbook"]
    for key in ("width_m", "depth_m"):
        positive(book[key], "cookbook "+key)
    speed(per_aspect_year(book["side_velocity_m_per_aspect_year"], cfg["aspect_year_s"]), "cookbook side velocity")
    ast = par["asthenosphere"]
    record(ast, "asthenosphere", ("name", "density_kg_m3", "heat_capacity_j_kg_k", "components"))
    material(ast["name"], {"role": "asthenosphere", "density_kg_m3": ast["density_kg_m3"],
                           "heat_capacity_j_kg_k": ast["heat_capacity_j_kg_k"], "components": ast["components"]})
    for key in ("interval_aspect_years", "exterior_source_mass_kg", "corner_offset_m"):
        positive(par[key], key)
    require(par["corner_offset_m"] < book["depth_m"], INVALID, "the corner offset must be smaller than the box depth")
    nonnegative(par["dissipation_j"], "dissipation")
    require(0 <= real(par["heat_fraction"], "heat fraction") <= 1, INVALID, "heat fraction must lie in [0, 1]")
    shifts = par["datum_shifts_k"]
    require(type(shifts) is list and shifts and all(nonnegative(s, "datum shift") != cfg["datum_k"] for s in shifts),
            INVALID, "datum shifts must be distinct from the declared datum")
    require(0 < real(par["under_balance_factor"], "under-balance factor") < 1, INVALID, "under-balance must lie in (0, 1)")
    require(-1 < real(par["surface_slope"], "surface slope") < 0, INVALID, "the control slope must lie in (-1, 0)")
    rev = par["reversed"]
    positive(rev["base_outward_velocity_m_per_aspect_year"], "reversed velocity")
    low, high = (temperature(t, "reversed range") for t in rev["cohort_temperature_range_k"])
    require(low <= temperature(rev["cohort_mean_temperature_k"], "mean") <= high
            and low <= temperature(rev["outgoing_temperature_k"], "outgoing") <= high
            and temperature(cfg["base_temperature_k"], "base") > high, INVALID,
            "the reversed cohort must contain its mean and outgoing states and exclude the inflow temperature")
    strip = par["strip"]
    positive(strip["reference_width_m"], "strip width")
    a, b, c = (real(strip[k], k) for k in ("stretch_compression", "stretch_start", "stretch_extension"))
    require(pol["stretch_window"][0] <= a < b < c <= pol["stretch_window"][1], INVALID,
            "strip stretches must satisfy compression < start < extension inside the window")
    positive(record(par["pure_shear"], "pure_shear", ("viscosity_pa_s",))["viscosity_pa_s"], "pure-shear viscosity")
    return True


def validate_case(spec):
    require(type(spec) is dict and set(spec) == CASE_FIELDS and spec.get("schema") == SCHEMA, INVALID,
            "basal-closure case schema or top-level fields mismatch")
    require(spec["status"] == "WORKING_NON_CANON", INVALID, "status must stay WORKING_NON_CANON")
    decision = spec["decision"]
    require(type(decision) is dict and decision.get("selected_law") == LAW, NOT_SELECTED, "selected law differs")
    require(spec["units"] == UNITS, UNIT, "declared units differ from the executable's SI conventions")
    require(spec["control_policy"] == POLICY, INVALID, "case policy and executable differ")
    require(spec["control_parameters"] == PARAMETERS, INVALID, "case parameters and executable differ")
    validate_parameters(spec["control_parameters"], spec["control_policy"])
    return spec


def load_case(path=CASE):
    return validate_case(json.loads(Path(path).read_text(encoding="utf-8")))


def retained_inputs():
    """Read-only JSON of the retained column (layers, densities, geotherm, heat properties) and strip windows."""
    weak, heat, strain = (json.loads((ROOT/name).read_text(encoding="utf-8")) for name in RETAINED)
    thermal = {layer["name"]: layer for layer in heat["thermal_layers"]}
    layers = [{"name": layer["name"], "thickness_m": layer["thickness_m"], "density_kg_m3": layer["density_kg_m3"],
               "temperature_k": list(layer["temperature_k"]),
               "heat_capacity_j_kg_k": thermal[layer["name"]]["heat_capacity_j_kg_k"],
               "radiogenic_w_m3": thermal[layer["name"]]["radiogenic_w_m3"]} for layer in weak["layers"]]
    return {"layers": layers, "gravity_m_s2": weak["representation"]["gravity_m_s2"],
            "top_k": heat["boundaries"]["top"]["value_k"], "bottom_k": heat["boundaries"]["bottom"]["value_k"],
            "surface_heat_flow_w_m2": heat["cookbook_constants"]["surface_heat_flow_w_m2"],
            "mantle_heat_flow_w_m2": heat["cookbook_constants"]["interface_heat_flow_w_m2"][-1],
            "temperature_window_k": strain["representation"]["temperature_window_k"],
            "stretch_window": strain["representation"]["stretch_window"]}


def check_retained(spec, ret):
    """The incoming state and windows must be those of the retained column and accepted strip, not new values."""
    par, pol = spec["control_parameters"], spec["control_policy"]
    cfg, ast, layers = par["configuration"], par["asthenosphere"], ret["layers"]
    temps = [layer["temperature_k"] for layer in layers]
    checks = (
        (math.fsum(layer["thickness_m"] for layer in layers) == cfg["lithosphere_thickness_m"], "lithosphere thickness"),
        (temps[0][0] == cfg["surface_temperature_k"] == ret["top_k"], "surface temperature"),
        (temps[-1][1] == cfg["base_temperature_k"] == ret["bottom_k"], "base temperature"),
        (all(a[1] == b[0] for a, b in zip(temps, temps[1:])), "continuous retained geotherm"),
        (all(layer["heat_capacity_j_kg_k"] == ast["heat_capacity_j_kg_k"] for layer in layers), "heat capacity"),
        (layers[-1]["density_kg_m3"] == ast["density_kg_m3"], "mantle density (cookbook background material)"),
        (ret["gravity_m_s2"] == cfg["gravity_m_s2"], "gravity"),
        (ret["temperature_window_k"] == pol["temperature_window_k"], "temperature window of the accepted strip"),
        (ret["stretch_window"] == pol["stretch_window"], "stretch window of the accepted strip"),
    )
    for ok, what in checks:
        require(ok, RETAINED_MISMATCH, what+" differs from the retained cases")
    return True


# ----------------------------------------------------------------------------- manufactured accounts (not solutions)

def material_table(spec, ret):
    ast = spec["control_parameters"]["asthenosphere"]
    table = {ast["name"]: {"role": "asthenosphere", "density_kg_m3": ast["density_kg_m3"],
                           "heat_capacity_j_kg_k": ast["heat_capacity_j_kg_k"], "components": dict(ast["components"])}}
    for layer in ret["layers"]:
        table[layer["name"]] = {"role": "continental_crust" if "crust" in layer["name"] else "mantle_lithosphere",
                                "density_kg_m3": layer["density_kg_m3"],
                                "heat_capacity_j_kg_k": layer["heat_capacity_j_kg_k"],
                                "components": {layer["name"]: 1.0}}
    return table


def column_rows(spec, ret, depth):
    """(cohort, material, thickness, top T, bottom T): retained lithosphere, then isothermal asthenosphere to depth."""
    par = spec["control_parameters"]
    cfg = par["configuration"]
    rows = [(layer["name"], layer["name"], layer["thickness_m"], *layer["temperature_k"]) for layer in ret["layers"]]
    if depth > cfg["lithosphere_thickness_m"]:
        rows.append(("asthenosphere-initial", par["asthenosphere"]["name"], depth-cfg["lithosphere_thickness_m"],
                     cfg["base_temperature_k"], cfg["base_temperature_k"]))
    return rows


def lithostatic(rows, mats, gravity):
    """Lithostatic pressure at the column base and its depth mean (exact for the piecewise-linear profile)."""
    pressure, pieces, depth = 0.0, [], 0.0
    for _, name, thickness, *_ in rows:
        top = pressure
        pressure = top+mats[name].density_kg_m3*gravity*thickness
        pieces.append((top+pressure)/2*thickness)
        depth += thickness
    return pressure, math.fsum(pieces)/depth


def configuration(spec, ret, *, consumer="i07_resolved", width=None, depth=None, side=None,
                  rule="reference_constant_volume", basal=None):
    par = spec["control_parameters"]
    cfg = par["configuration"]
    if side is None:
        side = per_aspect_year(cfg["side_velocity_m_per_aspect_year"], cfg["aspect_year_s"])
    config = {"law": LAW, "consumer": consumer, "width_m": cfg["width_m"] if width is None else width,
              "base_depth_m": cfg["base_depth_m"] if depth is None else depth,
              "lithosphere_thickness_m": cfg["lithosphere_thickness_m"],
              "segments": {name: {"normal": [n], "tangential": [t], "mesh": m}
                           for name, (n, t, m) in SELECTED_SEGMENTS.items()},
              "side_outward_velocity_m_s": [side, side], "basal_rule": rule, "materials": material_table(spec, ret),
              "incoming": {"material": par["asthenosphere"]["name"], "temperature_k": cfg["base_temperature_k"],
                           "temperature_kind": "actual", "phase": "solid"},
              "surface_temperature_k": cfg["surface_temperature_k"]}
    if basal is not None:
        config["basal_outward_velocity_m_s"] = basal
    return config


def box_account(spec, ret, *, width, depth, dt, parent, side_velocity=0.0, inflow_volume=0.0, base_outflow=None,
                surface_swept=0.0, asthenosphere_state=None):
    """Manufactured interval account for the rectangular box (a declared state, NOT a flow solution).

    The surface moves only by the declared uniform swept volume. Sides export the unthinned far-field column at its
    retained linear geotherm (the flux-weighted outgoing temperature of each layer is its mean). The base imports
    exterior asthenosphere, or exports `base_outflow = (volume, actual temperature)` from asthenosphere-initial.
    Conduction and radiogenic heat are the retained steady geotherm's. The ledger's gravity term is set to close, so
    this fixture cannot test the ledger's signs; pure_shear_work_control supplies independently derived terms.
    """
    par = spec["control_parameters"]
    cfg = par["configuration"]
    datum, t_base = cfg["datum_k"], cfg["base_temperature_k"]
    table = material_table(spec, ret)
    mats = materials_of(table)
    rows = column_rows(spec, ret, depth)
    cohorts = {}
    for name, mat_name, thickness, top, bottom in rows:
        mean, span = (top+bottom)/2, [top, bottom]
        if name == "asthenosphere-initial" and asthenosphere_state is not None:
            mean, span = asthenosphere_state
        mass = mats[mat_name].density_kg_m3*width*thickness
        cohorts[name] = {"material": mat_name, "mass_kg": mass, "energy_j": mass*mats[mat_name].specific_energy(mean, datum),
                         "temperature_range_k": list(span), "datum_k": datum}
    ast = mats[par["asthenosphere"]["name"]]
    stock = par["exterior_source_mass_kg"]
    streams = []
    if inflow_volume > 0:
        streams.append({"segment": "base", "direction": "in", "volume_m2": inflow_volume,
                        "source": "exterior-asthenosphere"})
    if base_outflow is not None:
        streams.append({"segment": "base", "direction": "out", "volume_m2": base_outflow[0],
                        "cohort": "asthenosphere-initial", "temperature_k": base_outflow[1],
                        "receiver": "exterior-asthenosphere-sink"})
    if side_velocity > 0:
        streams += [{"segment": side, "direction": "out", "volume_m2": side_velocity*dt*thickness, "cohort": name,
                     "temperature_k": (top+bottom)/2, "receiver": side+"-far-field"}
                    for side in ("left", "right") for name, _, thickness, top, bottom in rows]
    area_time = width*dt
    lithosphere_base = depth == cfg["lithosphere_thickness_m"]
    conduction = {"base": ret["mantle_heat_flow_w_m2"]*area_time if lithosphere_base else 0.0,  # isothermal below
                  "left": 0.0, "right": 0.0, "top": -ret["surface_heat_flow_w_m2"]*area_time}
    radiogenic = math.fsum(layer["radiogenic_w_m3"]*layer["thickness_m"] for layer in ret["layers"])*area_time
    p_base, p_side = lithostatic(rows, mats, cfg["gravity_m_s2"])
    side_volume = side_velocity*dt*depth
    base_flux = -inflow_volume+(base_outflow[0] if base_outflow is not None else 0.0)
    work = {"base": flow_work(-p_base, base_flux), "left": flow_work(-p_side, side_volume),
            "right": flow_work(-p_side, side_volume), "top": 0.0}
    dissipation = par["dissipation_j"]
    return {"law": LAW, "parent": parent, "interval_s": [0.0, dt], "datum_k": datum, "materials": table,
            "domain": {"volume_start_m2": width*depth, "volume_end_m2": width*depth+surface_swept, "cohorts": cohorts},
            "sources": {"exterior-asthenosphere": {"material": ast.name, "mass_kg": stock,
                                                   "energy_j": stock*ast.specific_energy(t_base, datum),
                                                   "temperature_k": t_base, "temperature_kind": "actual",
                                                   "phase": "solid", "datum_k": datum}},
            "receivers": ["left-far-field", "right-far-field", "exterior-asthenosphere-sink"],
            "segments": {"base": {"kind": "base", "mesh": "fixed", "swept_volume_m2": 0.0},
                         "left": {"kind": "side", "mesh": "tangential", "swept_volume_m2": 0.0},
                         "right": {"kind": "side", "mesh": "tangential", "swept_volume_m2": 0.0},
                         "top": {"kind": "surface", "mesh": "free_surface", "swept_volume_m2": surface_swept}},
            "streams": streams, "conduction_in_j": conduction,
            "interior": {"radiogenic_j": radiogenic, "dissipation_j": dissipation, "heat_fraction": par["heat_fraction"],
                         "gravity_work_j": dissipation-math.fsum(work.values())},
            "boundary_work_in_j": work}


def strip_account(spec, ret, interface, *, depth, dt, parent, outgoing=None, asthenosphere_state=None):
    """Manufactured insulated I05 open-base account at lam0 = 1 (a declared state, NOT a transport solution)."""
    par = spec["control_parameters"]
    cfg = par["configuration"]
    datum, t_base = cfg["datum_k"], cfg["base_temperature_k"]
    table = material_table(spec, ret)
    mats = materials_of(table)
    width = par["strip"]["reference_width_m"]
    cohorts = {}
    for name, mat_name, thickness, top, bottom in column_rows(spec, ret, depth):
        mean, span = (top+bottom)/2, [top, bottom]
        if name == "asthenosphere-initial" and asthenosphere_state is not None:
            mean, span = asthenosphere_state
        mass = mats[mat_name].density_kg_m3*width*thickness
        cohorts[name] = {"material": mat_name, "mass_kg": mass, "energy_j": mass*mats[mat_name].specific_energy(mean, datum),
                         "temperature_range_k": list(span), "datum_k": datum}
    ast = mats[par["asthenosphere"]["name"]]
    stock = par["exterior_source_mass_kg"]
    flux = interface["base_flux"]
    streams = []
    if flux["direction"] == "in":
        streams.append({"segment": "base", "direction": "in", "volume_m2": flux["volume_m2"],
                        "source": "exterior-asthenosphere"})
    elif flux["direction"] == "out":
        streams.append({"segment": "base", "direction": "out", "volume_m2": flux["volume_m2"],
                        "cohort": "asthenosphere-initial", "temperature_k": outgoing,
                        "receiver": "exterior-asthenosphere-sink"})
    return {"law": LAW, "parent": parent, "interval_s": [0.0, dt], "datum_k": datum, "materials": table,
            "domain": {"volume_start_m2": interface["volume_start_m2"], "volume_end_m2": interface["volume_end_m2"],
                       "cohorts": cohorts},
            "sources": {"exterior-asthenosphere": {"material": ast.name, "mass_kg": stock,
                                                   "energy_j": stock*ast.specific_energy(t_base, datum),
                                                   "temperature_k": t_base, "temperature_kind": "actual",
                                                   "phase": "solid", "datum_k": datum}},
            "receivers": ["exterior-asthenosphere-sink"], "segments": copy.deepcopy(interface["segments"]),
            "streams": streams, "conduction_in_j": {name: 0.0 for name in interface["segments"]},
            "interior": {"radiogenic_j": 0.0, "dissipation_j": 0.0, "heat_fraction": 1.0}}


def pure_shear_account(spec, field, dt, powers, parent):
    """Interval account of the exact pure-shear box: basal inflow a H over the width, side outflow a W/2 over the height.

    Its mechanical terms are the independently integrated powers times dt, never a closing value. Its thermal entries
    are a declared isothermal state at T_b with no conduction booked: not a thermal solution and not tested here.
    """
    par = spec["control_parameters"]
    cfg, ast = par["configuration"], par["asthenosphere"]
    datum, t = cfg["datum_k"], cfg["base_temperature_k"]
    table = {ast["name"]: {"role": "asthenosphere", "density_kg_m3": ast["density_kg_m3"],
                           "heat_capacity_j_kg_k": ast["heat_capacity_j_kg_k"], "components": dict(ast["components"])}}
    mat = material(ast["name"], table[ast["name"]])
    step = Fraction(dt)
    volume = float(field.width*field.height)
    mass, per_kg, stock = mat.density_kg_m3*volume, mat.specific_energy(t, datum), par["exterior_source_mass_kg"]
    inflow = float(field.a*field.height*field.width*step)
    side_out = float(field.a*field.width/2*field.height*step)
    return {"law": LAW, "parent": parent, "interval_s": [0.0, dt], "datum_k": datum, "materials": table,
            "domain": {"volume_start_m2": volume, "volume_end_m2": volume,
                       "cohorts": {"asthenosphere-initial": {"material": mat.name, "mass_kg": mass,
                                                              "energy_j": mass*per_kg, "temperature_range_k": [t, t],
                                                              "datum_k": datum}}},
            "sources": {"exterior-asthenosphere": {"material": mat.name, "mass_kg": stock, "energy_j": stock*per_kg,
                                                   "temperature_k": t, "temperature_kind": "actual", "phase": "solid",
                                                   "datum_k": datum}},
            "receivers": ["left-far-field", "right-far-field"],
            "segments": {"base": {"kind": "base", "mesh": "fixed", "swept_volume_m2": 0.0},
                         "left": {"kind": "side", "mesh": "tangential", "swept_volume_m2": 0.0},
                         "right": {"kind": "side", "mesh": "tangential", "swept_volume_m2": 0.0},
                         "top": {"kind": "surface", "mesh": "free_surface", "swept_volume_m2": 0.0}},
            "streams": [{"segment": "base", "direction": "in", "volume_m2": inflow, "source": "exterior-asthenosphere"}]
                       + [{"segment": side, "direction": "out", "volume_m2": side_out, "cohort": "asthenosphere-initial",
                           "temperature_k": t, "receiver": side+"-far-field"} for side in ("left", "right")],
            "conduction_in_j": {"base": 0.0, "left": 0.0, "right": 0.0, "top": 0.0},
            "interior": {"radiogenic_j": 0.0, "dissipation_j": float(powers["dissipation"]*step),
                         "heat_fraction": par["heat_fraction"], "gravity_work_j": float(powers["gravity"]*step)},
            "boundary_work_in_j": {name: float(powers[name]*step) for name in ("base", "left", "right", "top")}}


def shift_datum(account, new_datum):
    """The same physical account at another caloric datum: each stored energy moves by M Cp (T_ref - T_new)."""
    shifted = copy.deepcopy(account)
    old, mats = account["datum_k"], account["materials"]
    shifted["datum_k"] = new_datum
    for group in (shifted["domain"]["cohorts"], shifted["sources"]):
        for item in group.values():
            item["energy_j"] = item["energy_j"]+item["mass_kg"]*mats[item["material"]]["heat_capacity_j_kg_k"]*(old-new_datum)
            item["datum_k"] = new_datum
    return shifted


def end_state_of(account, proposal):
    """A consistent supplied end state (a control input, not a solution): each start cohort plus its booked delta, each
    new cohort, and the total caloric energy as start plus the booked change."""
    cohorts = account["domain"]["cohorts"]
    mass = {name: item["mass_kg"]+proposal["domain"]["cohorts"].get(name, {"mass_kg": 0.0})["mass_kg"]
            for name, item in cohorts.items()}
    mass.update({name: item["mass_kg"] for name, item in proposal["domain"]["new_cohorts"].items()})
    energy = math.fsum([item["energy_j"] for item in cohorts.values()]+[proposal["domain"]["energy_j"]])
    return mass, energy


# ----------------------------------------------------------------------------- independent exact oracle

def exact_booking(account):
    """Exact rational booking (fractions.Fraction) of a supplied account's streams and heat terms.

    Shares no arithmetic with propose_interval: every float input is converted exactly and summed without rounding.
    """
    F = Fraction
    mats, datum = account["materials"], F(account["datum_k"])
    sources, cohorts = account["sources"], account["domain"]["cohorts"]
    out = {"mass": F(0), "energy": F(0), "components": {}, "sources": {}, "receivers": {}, "mass_scale": F(0),
           "energy_scale": F(0)}
    for item in account["streams"]:
        inflow = item["direction"] == "in"
        mat = mats[sources[item["source"]]["material"] if inflow else cohorts[item["cohort"]]["material"]]
        t = F(sources[item["source"]]["temperature_k"] if inflow else item["temperature_k"])
        kg = F(mat["density_kg_m3"])*F(item["volume_m2"])
        joules = kg*F(mat["heat_capacity_j_kg_k"])*(t-datum)
        sign = 1 if inflow else -1
        out["mass"] += sign*kg
        out["energy"] += sign*joules
        out["mass_scale"] += kg
        out["energy_scale"] += abs(joules)
        for comp, frac in mat["components"].items():
            out["components"][comp] = out["components"].get(comp, F(0))+sign*kg*F(frac)
        book, key = (out["sources"], item["source"]) if inflow else (out["receivers"], item["receiver"])
        mass, energy = book.get(key, (F(0), F(0)))
        book[key] = (mass+kg, energy+joules)
    inner = account["interior"]
    heat = [F(v) for v in account["conduction_in_j"].values()]+[F(inner["radiogenic_j"]),
                                                                 F(inner["heat_fraction"])*F(inner["dissipation_j"])]
    out["energy"] += sum(heat)
    out["energy_scale"] += sum(abs(h) for h in heat)
    return out


def agree(value, exact, scale):
    """|float - exact| within oracle_relative of an exact gross scale (exact equality when the scale is zero)."""
    return abs(Fraction(value)-exact) <= Fraction(POLICY["oracle_relative"])*scale


def refusal_code(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except Refusal as exc:
        return exc.code
    return None


def finish(checks, **data):
    checks = {name: bool(value) for name, value in checks.items()}
    return dict(passed=all(checks.values()), checks=checks, **data)


def check_deadline(deadline):
    if deadline is not None and time.perf_counter() > deadline:
        raise RuntimeError("cooperative time budget exhausted; nothing further run")


# ----------------------------------------------------------------------------- controls (frozen before execution)

def reference_numbers(spec):
    par = spec["control_parameters"]
    cfg = par["configuration"]
    side = per_aspect_year(cfg["side_velocity_m_per_aspect_year"], cfg["aspect_year_s"])
    return par, cfg, side, par["interval_aspect_years"]*ASPECT_YEAR_S


def constant_volume_control(spec, ret, deadline=None):
    """The constant-volume special case: ASPECT's literal rule and the selected deeper box, against exact oracles."""
    check_deadline(deadline)
    par, cfg, side, dt = reference_numbers(spec)
    book, F = par["cookbook"], Fraction
    literal = F(book["side_velocity_m_per_aspect_year"])*2*F(book["depth_m"])/F(book["width_m"])      # v*2*d/w, m/yr
    book_side = per_aspect_year(book["side_velocity_m_per_aspect_year"], cfg["aspect_year_s"])
    book_config = configuration(spec, ret, consumer="i05_accounts", width=book["width_m"], depth=book["depth_m"],
                                side=book_side)
    book_inflow = -resolved_prescription(book_config)["segments"]["base"]["normal"]["outward_velocity_m_s"]
    book_refused = refusal_code(resolved_prescription, dict(book_config, consumer="i07_resolved"))
    book_account = box_account(spec, ret, width=book["width_m"], depth=book["depth_m"], dt=dt, parent="cookbook-box",
                               side_velocity=book_side, inflow_volume=book_inflow*book["width_m"]*dt)
    book_proposal, book_exact = propose_interval(book_account), exact_booking(book_account)
    rule = resolved_prescription(configuration(spec, ret))
    inflow = -rule["segments"]["base"]["normal"]["outward_velocity_m_s"]
    account = box_account(spec, ret, width=cfg["width_m"], depth=cfg["base_depth_m"], dt=dt, parent="selected-box",
                          side_velocity=side, inflow_volume=inflow*cfg["width_m"]*dt)
    proposal, exact = propose_interval(account), exact_booking(account)
    # Independent closed form: at constant volume dense asthenosphere replaces the lighter crust leaving through both
    # sides, so the domain gains 2 v dt sum (rho_a - rho_i) h_i. Constant volume is not constant mass.
    rho_a = F(par["asthenosphere"]["density_kg_m3"])
    gain = 2*F(side)*F(dt)*sum((rho_a-F(layer["density_kg_m3"]))*F(layer["thickness_m"]) for layer in ret["layers"])
    checks = {
        "cookbook_rule_is_the_literal_expression": agree(book_inflow*ASPECT_YEAR_S, literal, literal),
        "cookbook_base_refused_for_separation": book_refused == NO_LAYER,
        "cookbook_inflow_equals_side_outflow": book_proposal["volume"]["inflow_equals_outflow"],
        "cookbook_mass_matches_oracle": agree(book_proposal["domain"]["mass_kg"], book_exact["mass"],
                                              book_exact["mass_scale"]),
        "cookbook_energy_matches_oracle": agree(book_proposal["domain"]["energy_j"], book_exact["energy"],
                                                book_exact["energy_scale"]),
        "cookbook_gain_is_closed_form": agree(book_proposal["domain"]["mass_kg"], gain, book_exact["mass_scale"]),
        "selected_rule_is_closed_form": agree(inflow, 2*F(side)*F(cfg["base_depth_m"])/F(cfg["width_m"]), F(inflow)),
        "selected_admitted_for_separation": rule["status"] == PRESCRIPTION_ONLY,
        "selected_inflow_equals_side_outflow": proposal["volume"]["inflow_equals_outflow"],
        "selected_volume_constant": closes(proposal["volume"]["change_m2"], proposal["volume"]["scale_m2"]),
        "selected_mass_matches_oracle": agree(proposal["domain"]["mass_kg"], exact["mass"], exact["mass_scale"]),
        "constant_volume_is_not_constant_mass": gain > 0 and agree(proposal["domain"]["mass_kg"], gain,
                                                                   exact["mass_scale"]),
        "selected_energy_matches_oracle": agree(proposal["domain"]["energy_j"], exact["energy"], exact["energy_scale"]),
        # The fixture sets its gravity term to close the ledger: this is not a sign test (see pure_shear_work_control).
        "manufactured_ledger_closes_by_construction": proposal["mechanical"]["status"] == "CLOSED",
    }
    return finish(checks, manufactured=True, stokes_solution=False,
                  cookbook_basal_inflow_m_per_aspect_year=book_inflow*ASPECT_YEAR_S,
                  selected_basal_inflow_m_per_aspect_year=inflow*ASPECT_YEAR_S,
                  inflow_volume_m2=proposal["volume"]["inflow_m2"], outflow_volume_m2=proposal["volume"]["outflow_m2"],
                  domain_mass_change_kg=proposal["domain"]["mass_kg"], closed_form_mass_change_kg=float(gain),
                  domain_energy_change_j=proposal["domain"]["energy_j"],
                  cookbook_domain_energy_change_j=book_proposal["domain"]["energy_j"])


def moving_surface_control(spec, ret, deadline=None):
    """A moving impermeable surface changes the domain volume; mesh conventions decide which fluxes appear."""
    check_deadline(deadline)
    par, cfg, side, dt = reference_numbers(spec)
    width, depth, F = cfg["width_m"], cfg["base_depth_m"], Fraction
    # (a) Under-balanced uniform inflow: the surface subsides uniformly; no material crosses it.
    outflow = 2*side*depth*dt
    inflow = par["under_balance_factor"]*outflow
    drop = (outflow-inflow)/width
    before = polygon_area([(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)])
    after = polygon_area([(0.0, 0.0), (width, 0.0), (width, depth-drop), (0.0, depth-drop)])
    moving = volume_account(before, after, [0.0, 0.0, 0.0, after-before], [inflow], [outflow])
    stationary = refusal_code(volume_account, before, after, [0.0]*4, [inflow], [outflow])
    corrected = refusal_code(volume_account, before, after, [0.0, 0.0, 0.0, after-before], [outflow], [outflow])
    # (b) ASPECT's literal rule keeps 2 v d of basal inflow while its tangential side mesh lets the side height follow
    # the free-surface corners: a flat offset eta relaxes as eta0 exp(-2 v t / W) (Atlas derivation, not an ASPECT run).
    book = par["cookbook"]
    v = per_aspect_year(book["side_velocity_m_per_aspect_year"], cfg["aspect_year_s"])
    w, d, eta0 = book["width_m"], book["depth_m"], par["corner_offset_m"]
    eta1 = eta0*math.exp(-2*v/w*dt)
    corner_out = 2*v*d*dt-w*eta0*math.expm1(-2*v/w*dt)
    v0 = polygon_area([(0.0, 0.0), (w, 0.0), (w, d+eta0), (0.0, d+eta0)])
    v1 = polygon_area([(0.0, 0.0), (w, 0.0), (w, d+eta1), (0.0, d+eta1)])
    corner = volume_account(v0, v1, [0.0, 0.0, 0.0, v1-v0], [2*v*d*dt], [corner_out])
    # (c) One pure-shear flow in two conventions: material-following sides (the I05 strip) and a fixed box.
    strip = par["strip"]
    w0, lam0, lam1 = strip["reference_width_m"], strip["stretch_start"], strip["stretch_extension"]
    face = strip_open_base(route="open_base", reference_width_m=w0, base_depth_m=depth,
                           lithosphere_thickness_m=cfg["lithosphere_thickness_m"], stretch_start=lam0, stretch_end=lam1)
    material_sides = volume_account(face["volume_start_m2"], face["volume_end_m2"],
                                    [s["swept_volume_m2"] for s in face["segments"].values()],
                                    [face["base_flux"]["volume_m2"]], [])
    euler = w0*depth*math.log(lam1/lam0)
    fixed_sides = volume_account(w0*depth, w0*depth, [0.0]*4, [euler], [euler/2, euler/2])
    # (d) Free-surface convention: horizontal material motion under a sloping surface.
    slope = par["surface_slope"]
    top = Segment(width, depth+slope*width, 0.0, depth)
    motion = (side, 0.0)
    normal = top.crossing_rate(motion, top.normal_projection(motion))
    crossing = top.crossing_rate(motion, (0.0, motion[1]))*dt       # mesh takes only the vertical component
    erosion = box_account(spec, ret, width=width, depth=depth, dt=dt, parent="surface-convention",
                          surface_swept=-crossing)
    erosion["streams"] = [{"segment": "top", "direction": "out", "volume_m2": crossing,
                           "cohort": ret["layers"][0]["name"], "temperature_k": cfg["surface_temperature_k"],
                           "receiver": "surface-process-sink"}]
    erosion["receivers"].append("surface-process-sink")
    unowned = refusal_code(propose_interval, erosion)
    owned = mutated(erosion, (("segments", "top", "owner"), "surface-process"))
    owned_proposal = propose_interval(owned)
    closed_form = -F(slope)*F(side)*F(width)*F(dt)
    checks = {
        "moving_surface_closes": closes(moving["change_m2"]-(inflow-outflow), moving["scale_m2"]),
        "moving_surface_breaks_the_equality": not moving["inflow_equals_outflow"],
        "stationary_surface_claim_refused": stationary == VOLUME,
        "after_the_fact_flux_correction_refused": corrected == VOLUME,
        "corner_offset_closes": closes(corner["change_m2"]-w*(eta1-eta0), corner["scale_m2"]),
        "corner_offset_breaks_the_equality": not corner["inflow_equals_outflow"],
        "material_sides_have_no_side_flux": material_sides["outflow_m2"] == 0 and not material_sides["inflow_equals_outflow"],
        "fixed_sides_balance": fixed_sides["inflow_equals_outflow"],
        "conventions_book_different_base_inflow": abs(face["base_flux"]["volume_m2"]-euler) > 0.05*euler,
        "normal_projection_is_impermeable": closes(normal, abs(side)*math.hypot(width, slope*width)),
        "vertical_mesh_crossing_matches_closed_form": crossing > 0 and agree(crossing, closed_form, closed_form),
        "unowned_crossing_refused": unowned == SURFACE,
        "owned_exchange_booked": owned_proposal["receivers"]["surface-process-sink"]["mass_kg"] > 0,
    }
    return finish(checks, manufactured=True, stokes_solution=False,
                  under_balanced_volume_change_m2=moving["change_m2"], surface_drop_m=drop,
                  corner_volume_change_m2=corner["change_m2"], corner_end_offset_m=eta1,
                  material_sides_inflow_m2=face["base_flux"]["volume_m2"], fixed_box_inflow_m2=euler,
                  vertical_mesh_crossing_m2=crossing)


def flow_direction_control(spec, ret, deadline=None):
    """Zero flow, reversed (outgoing) base flow and ownership of the outgoing state."""
    check_deadline(deadline)
    par, cfg, side, dt = reference_numbers(spec)
    width, depth, datum, F = cfg["width_m"], cfg["base_depth_m"], cfg["datum_k"], Fraction
    rev = par["reversed"]
    still_rule = resolved_prescription(configuration(spec, ret, side=0.0))
    still = box_account(spec, ret, width=width, depth=depth, dt=dt, parent="zero-flow")
    still_before = copy.deepcopy(still)
    still_proposal, still_exact = propose_interval(still), exact_booking(still)
    u_out = per_aspect_year(rev["base_outward_velocity_m_per_aspect_year"], cfg["aspect_year_s"])
    reversed_rule = resolved_prescription(configuration(spec, ret, side=0.0, rule="declared_uniform", basal=u_out))
    volume = u_out*width*dt
    reverse = box_account(spec, ret, width=width, depth=depth, dt=dt, parent="reversed", surface_swept=-volume,
                          base_outflow=(volume, rev["outgoing_temperature_k"]),
                          asthenosphere_state=(rev["cohort_mean_temperature_k"], rev["cohort_temperature_range_k"]))
    source_before = copy.deepcopy(reverse["sources"])
    reverse_proposal, reverse_exact = propose_interval(reverse), exact_booking(reverse)
    reset = mutated(reverse, (("streams", 0, "temperature_k"), cfg["base_temperature_k"]))
    to_source = mutated(reverse, (("streams", 0, "receiver"), "exterior-asthenosphere"))
    to_source["receivers"].append("exterior-asthenosphere")
    missing = mutated(reverse, (("streams", 0, "temperature_k"), DELETE))
    # Conductive heat through the base: zero-flux where rock leaves, Dirichlet where nothing crosses.
    warmed_outflow = mutated(reverse, (("conduction_in_j", "base"), 1e12))
    warmed_before = copy.deepcopy(warmed_outflow)
    warmed_code = refusal_code(propose_interval, warmed_outflow)
    warmed_still = propose_interval(mutated(still, (("conduction_in_j", "base"), 1e12)))
    cp = par["asthenosphere"]["heat_capacity_j_kg_k"]
    part = reverse_proposal["receivers"]["exterior-asthenosphere-sink"]["parts"][0]
    per_kg = F(cp)*(F(rev["outgoing_temperature_k"])-F(datum))
    base_still, base_rev = still_rule["segments"]["base"], reversed_rule["segments"]["base"]
    checks = {
        "zero_flow_base_is_impermeable": base_still["flow"] == "impermeable",
        "zero_flow_temperature_is_conductive_only": base_still["temperature"]["type"] == "dirichlet"
                                                   and base_still["composition"]["type"] == "natural",
        "zero_flow_moves_nothing": not still_proposal["sources"] and not still_proposal["receivers"]
                                   and still_proposal["domain"]["mass_kg"] == 0,
        "zero_flow_heat_is_conduction_and_sources": agree(still_proposal["domain"]["energy_j"], still_exact["energy"],
                                                          still_exact["energy_scale"]),
        "zero_flow_input_unchanged": still == still_before,
        "reversed_base_is_outflow": base_rev["flow"] == "outflow",
        "reversed_base_has_no_dirichlet": base_rev["temperature"]["type"] == "zero_conductive_flux"
                                          and base_rev["composition"]["type"] == "natural",
        "reversed_source_untouched": not reverse_proposal["sources"] and reverse["sources"] == source_before,
        "reversed_receiver_matches_oracle": agree(reverse_proposal["receivers"]["exterior-asthenosphere-sink"]["energy_j"],
                                                  reverse_exact["receivers"]["exterior-asthenosphere-sink"][1],
                                                  reverse_exact["energy_scale"]),
        "outgoing_state_is_the_actual_state": part["temperature_k"] == rev["outgoing_temperature_k"]
                                              and agree(part["energy_j"]/part["mass_kg"], per_kg, per_kg),
        "reset_to_boundary_temperature_refused": refusal_code(propose_interval, reset) == OUTFLOW,
        "outflow_into_the_source_refused": refusal_code(propose_interval, to_source) == OUTFLOW,
        "missing_outgoing_state_refused": refusal_code(propose_interval, missing) == OUTFLOW,
        "reversed_volume_falls": reverse_proposal["volume"]["change_m2"] < 0,
        "outflow_base_conduction_refused": warmed_code == THERMAL_BOUNDARY and warmed_outflow == warmed_before,
        "impermeable_base_conduction_admitted": warmed_still["thermal"]["conduction_in_j"]["base"] == 1e12,
        "accounts_apply_the_prescribed_base_condition":
            still_proposal["thermal"]["boundary_conditions"]["base"] == base_still["temperature"]["type"] == "dirichlet"
            and reverse_proposal["thermal"]["boundary_conditions"]["base"] == base_rev["temperature"]["type"]
            == "zero_conductive_flux",
    }
    return finish(checks, manufactured=True, stokes_solution=False,
                  zero_flow_energy_change_j=still_proposal["domain"]["energy_j"],
                  reversed_outflow_volume_m2=volume, reversed_outflow_energy_j=part["energy_j"],
                  reversed_outgoing_temperature_k=part["temperature_k"])


def accounts_control(spec, ret, deadline=None):
    """Mass, component and caloric balances against the exact oracle; datum invariance; flow work kept out of heat."""
    check_deadline(deadline)
    par, cfg, side, dt = reference_numbers(spec)
    width, depth, datum, F = cfg["width_m"], cfg["base_depth_m"], cfg["datum_k"], Fraction
    inflow_volume = 2*side*depth/width*width*dt
    account = box_account(spec, ret, width=width, depth=depth, dt=dt, parent="accounts", side_velocity=side,
                          inflow_volume=inflow_volume)
    proposal, exact = propose_interval(account), exact_booking(account)
    mass_scale, energy_scale = exact["mass_scale"], exact["energy_scale"]
    # Exact rational inventories: the start cohorts at their reference densities, then plus inflow minus outflow.
    table = account["materials"]
    inventory = sum(F(item["mass_kg"])/F(table[item["material"]]["density_kg_m3"])
                    for item in account["domain"]["cohorts"].values())
    end_inventory = inventory+sum((1 if item["direction"] == "in" else -1)*F(item["volume_m2"])
                                  for item in account["streams"])
    components_ok = set(proposal["domain"]["components_kg"]) == set(exact["components"]) and all(
        agree(proposal["domain"]["components_kg"][c], value, mass_scale) for c, value in exact["components"].items())
    sources_ok = set(proposal["sources"]) == set(exact["sources"]) and all(
        agree(-proposal["sources"][s]["mass_kg"], m, mass_scale) and agree(-proposal["sources"][s]["energy_j"], e,
                                                                           energy_scale)
        for s, (m, e) in exact["sources"].items())
    receivers_ok = set(proposal["receivers"]) == set(exact["receivers"]) and all(
        agree(proposal["receivers"][r]["mass_kg"], m, mass_scale) and agree(proposal["receivers"][r]["energy_j"], e,
                                                                            energy_scale)
        for r, (m, e) in exact["receivers"].items())
    debit = math.fsum(-row["mass_kg"] for row in proposal["sources"].values())
    credit = math.fsum(row["mass_kg"] for row in proposal["receivers"].values())
    transfers_ok = closes(proposal["domain"]["mass_kg"]-(debit-credit), float(mass_scale)) and closes(
        proposal["thermal"]["advected_in_j"]-math.fsum(-row["energy_j"] for row in proposal["sources"].values()),
        float(energy_scale))
    capacity = exact_capacity_flux(account)
    shifts = {}
    for new in par["datum_shifts_k"]:
        moved_account = shift_datum(account, new)
        moved, moved_exact = propose_interval(moved_account), exact_booking(moved_account)
        shift = F(moved["domain"]["energy_j"])-F(proposal["domain"]["energy_j"])
        expected = (F(datum)-F(new))*capacity
        shifts[str(new)] = {
            "mass_identical": moved["domain"]["mass_kg"] == proposal["domain"]["mass_kg"],
            "energy_matches_oracle": agree(moved["domain"]["energy_j"], moved_exact["energy"],
                                           moved_exact["energy_scale"]),
            "shift_is_capacity_times_datum_change": abs(shift-expected) <= F(POLICY["oracle_relative"])*(
                energy_scale+moved_exact["energy_scale"]),
            "energy_change_j": moved["domain"]["energy_j"]}
    mixed = mutated(account, (("sources", "exterior-asthenosphere", "datum_k"), 0.0))
    mats = materials_of(account["materials"])
    ast = mats[par["asthenosphere"]["name"]]
    p_base, _ = lithostatic(column_rows(spec, ret, depth), mats, cfg["gravity_m_s2"])
    t_base = cfg["base_temperature_k"]
    twice = ast.density_kg_m3*inflow_volume*(specific_enthalpy(ast, t_base, p_base, datum)-ast.specific_energy(t_base,
                                                                                                                 datum))
    work = flow_work(-p_base, -inflow_volume)
    stock = account["sources"]["exterior-asthenosphere"]["mass_kg"]
    enthalpy_source = mutated(account, (("sources", "exterior-asthenosphere", "energy_j"),
                                        stock*specific_enthalpy(ast, t_base, p_base, datum)))
    gravity = account["interior"]["gravity_work_j"]
    checks = {
        "start_inventory_fills_the_domain": agree(proposal["volume"]["inventory_start_m2"], inventory, inventory)
                                            and agree(account["domain"]["volume_start_m2"], inventory, inventory),
        "end_inventory_fills_the_end_domain": agree(proposal["volume"]["inventory_end_m2"], end_inventory, inventory)
                                              and agree(account["domain"]["volume_end_m2"], end_inventory, inventory),
        "domain_mass_matches_oracle": agree(proposal["domain"]["mass_kg"], exact["mass"], mass_scale),
        "components_match_oracle": components_ok,
        "source_debits_match_oracle": sources_ok,
        "receiver_credits_match_oracle": receivers_ok,
        "transfers_consistent_between_accounts": transfers_ok,
        "caloric_change_matches_oracle": agree(proposal["domain"]["energy_j"], exact["energy"], energy_scale),
        "datum_shifts_consistent": all(all(v for k, v in row.items() if k != "energy_change_j") for row in shifts.values()),
        "mixed_datum_refused": refusal_code(propose_interval, mixed) == DATUM,
        "enthalpy_minus_energy_is_flow_work": abs(twice-work) <= POLICY["oracle_relative"]*abs(work) and work > 0,
        "flow_work_is_booked_as_work": account["boundary_work_in_j"]["base"] == work,
        "enthalpy_source_refused": refusal_code(propose_interval, enthalpy_source) == SOURCE_STATE,
        "boundary_work_as_heat_refused": refusal_code(propose_interval, mutated(
            account, (("interior", "boundary_work_j"), work))) == THERMAL,
        "latent_heat_refused": refusal_code(propose_interval, mutated(account, (("interior", "latent_j"), 1.0))) == THERMAL,
        "open_ledger_refused": refusal_code(propose_interval, mutated(
            account, (("interior", "gravity_work_j"), gravity*(1+1e-6)))) == LEDGER,
        "surface_work_refused": refusal_code(propose_interval, mutated(
            account, (("boundary_work_in_j", "top"), 1.0))) == LEDGER,
    }
    return finish(checks, manufactured=True, stokes_solution=False, datum_k=datum, datum_shifts=shifts,
                  domain_mass_change_kg=proposal["domain"]["mass_kg"], caloric_change_j=proposal["domain"]["energy_j"],
                  basal_flow_work_j=work, flow_work_counted_twice_if_enthalpy_were_heat_j=twice,
                  base_pressure_pa=p_base)


DELETE = object()


def mutated(original, *changes):
    """A deep copy with nested (path, value) changes; DELETE removes the key. The original is never touched."""
    item = copy.deepcopy(original)
    for path, value in changes:
        target = item
        for key in path[:-1]:
            target = target[key]
        if value is DELETE:
            del target[path[-1]]
        else:
            target[path[-1]] = value
    return item


def exact_capacity_flux(account):
    """Exact net heat-capacity flux sum(sign rho Cp V) of the streams: moving the datum by dT changes the booked
    caloric change by exactly -dT times it (conduction and interior sources do not depend on the datum)."""
    total = Fraction(0)
    for item in account["streams"]:
        inflow = item["direction"] == "in"
        name = (account["sources"][item["source"]] if inflow else account["domain"]["cohorts"][item["cohort"]])["material"]
        mat = account["materials"][name]
        total += (1 if inflow else -1)*Fraction(mat["density_kg_m3"])*Fraction(mat["heat_capacity_j_kg_k"])*Fraction(
            item["volume_m2"])
    return total


def exhaustion_control(spec, ret, deadline=None):
    """A finite exterior source: exact depletion is accepted; any overdraft, including a joint one, is refused whole."""
    check_deadline(deadline)
    par, cfg, side, dt = reference_numbers(spec)
    width, depth, datum = cfg["width_m"], cfg["base_depth_m"], cfg["datum_k"]
    volume = per_aspect_year(par["reversed"]["base_outward_velocity_m_per_aspect_year"], cfg["aspect_year_s"])*width*dt
    account = box_account(spec, ret, width=width, depth=depth, dt=dt, parent="exhaustion", inflow_volume=volume,
                          surface_swept=volume)
    del account["boundary_work_in_j"], account["interior"]["gravity_work_j"]
    ast = materials_of(account["materials"])[par["asthenosphere"]["name"]]
    per_kg = ast.specific_energy(cfg["base_temperature_k"], datum)
    demand = ast.density_kg_m3*volume                           # formed exactly as propose_interval forms it

    def stocked(item, mass):
        return mutated(item, (("sources", "exterior-asthenosphere", "mass_kg"), mass),
                       (("sources", "exterior-asthenosphere", "energy_j"), mass*per_kg))

    exact_stock = stocked(account, demand)
    depleted = propose_interval(exact_stock)
    short = stocked(account, math.nextafter(demand, 0.0))
    short_before = copy.deepcopy(short)
    short_code = refusal_code(propose_interval, short)
    split = stocked(account, 0.75*demand)                       # each half fits; both together do not
    split["segments"] = {"base-west": {"kind": "base", "mesh": "fixed", "swept_volume_m2": 0.0},
                         "base-east": {"kind": "base", "mesh": "fixed", "swept_volume_m2": 0.0},
                         **{k: v for k, v in split["segments"].items() if k != "base"}}
    split["conduction_in_j"] = {"base-west": 0.0, "base-east": 0.0,
                                **{k: v for k, v in split["conduction_in_j"].items() if k != "base"}}
    split["streams"] = [{"segment": name, "direction": "in", "volume_m2": volume/2, "source": "exterior-asthenosphere"}
                        for name in ("base-west", "base-east")]
    joint_code = refusal_code(propose_interval, split)
    single = mutated(split, (("streams",), split["streams"][:1]), (("segments", "top", "swept_volume_m2"), volume/2),
                     (("domain", "volume_end_m2"), split["domain"]["volume_start_m2"]+volume/2))
    single_debit = propose_interval(single)["sources"]["exterior-asthenosphere"]["mass_kg"]
    layer = width*(depth-cfg["lithosphere_thickness_m"])
    overdraft = box_account(spec, ret, width=width, depth=depth, dt=dt, parent="overdraft", surface_swept=-1.01*layer,
                            base_outflow=(1.01*layer, cfg["base_temperature_k"]))
    row = depleted["sources"]["exterior-asthenosphere"]
    checks = {
        "exact_depletion_accepted": row["remaining_mass_kg"] == 0.0 and row["remaining_energy_j"] == 0.0,
        "one_ulp_overdraft_refused": short_code == EXHAUSTED,
        "refused_input_unchanged": short == short_before,
        "joint_overdraft_refused": joint_code == EXHAUSTED,
        "each_stream_alone_fits": single_debit == -ast.density_kg_m3*(volume/2),
        "cohort_overdraft_refused": refusal_code(propose_interval, overdraft) == OUTFLOW,
        "repeat_is_identical": propose_interval(exact_stock) == depleted,
    }
    return finish(checks, manufactured=True, stokes_solution=False, stock_kg=demand, inflow_volume_m2=volume,
                  joint_demand_kg=2*ast.density_kg_m3*(volume/2), joint_stock_kg=0.75*demand)


def refusals_control(spec, ret, deadline=None):
    """Incompatible mechanical data and invalid, nonfinite, unit or sign inputs are refused before any output."""
    check_deadline(deadline)
    par, cfg, side, dt = reference_numbers(spec)
    config = configuration(spec, ret)
    ocean = {"role": "oceanic_crust", "density_kg_m3": 2900.0, "heat_capacity_j_kg_k": 750.0,
             "components": {"basalt": 1.0}}
    closed_lid = [(("segments", "top", "normal"), ["velocity"]), (("top_outward_velocity_m_s",), 0.0)]
    prescription_cases = {
        "velocity_and_traction_on_one_component": ([(("segments", "base", "normal"), ["velocity", "traction"])],
                                                   OVERDETERMINED),
        "no_condition_on_a_component": ([(("segments", "base", "tangential"), [])], UNDERDETERMINED),
        "base_tangential_velocity": ([(("segments", "base", "tangential"), ["velocity"])], NOT_SELECTED),
        "base_moving_with_material": ([(("segments", "base", "mesh"), "material")], NOT_SELECTED),
        "closed_lid_pressure_nullspace": (closed_lid, NULLSPACE),
        "closed_lid_incompatible_flux": (closed_lid+[(("basal_rule",), "declared_uniform"),
                                                     (("basal_outward_velocity_m_s",), -1e-12)], INCOMPATIBLE_FLUX),
        "total_flux_without_distribution": ([(("basal_rule",), "total_flux")], LOCAL_FIELD),
        "base_at_the_lithosphere_base": ([(("base_depth_m",), cfg["lithosphere_thickness_m"])], NO_LAYER),
        "potential_temperature": ([(("incoming", "temperature_kind"), "potential")], POTENTIAL),
        "melt_bearing_inflow": ([(("incoming", "phase"), "partially_molten")], MELT),
        "instant_ocean_crust": ([(("materials", "new-ocean-crust"), ocean), (("incoming", "material"), "new-ocean-crust")],
                                NOT_ASTHENOSPHERE),
        "side_inflow": ([(("side_outward_velocity_m_s",), [-side, side])], SIDE_INFLOW),
        "nonfinite_width": ([(("width_m",), math.nan)], INVALID),
        "boolean_width": ([(("width_m",), True)], INVALID),
        "unknown_field": ([(("extra",), 1)], INVALID),
        "m_per_year_passed_as_m_per_s": ([(("side_outward_velocity_m_s",), [0.0025, 0.0025])], WINDOW),
        "celsius_offset_added_twice": ([(("incoming", "temperature_k"), 1613.0+273.15)], WINDOW),
        "another_law": ([(("law",), "atlas.other")], NOT_SELECTED),
        "reference_rule_with_supplied_velocity": ([(("basal_outward_velocity_m_s",), -1e-11)], INVALID),
    }
    account = box_account(spec, ret, width=cfg["width_m"], depth=cfg["base_depth_m"], dt=dt, parent="refusals",
                          side_velocity=side, inflow_volume=2*side*cfg["base_depth_m"]*dt)
    gravity = account["interior"]["gravity_work_j"]
    stored = account["sources"]["exterior-asthenosphere"]["energy_j"]
    start = account["domain"]["volume_start_m2"]
    doubled = [(("domain", "cohorts", name, key), 2*item[key]) for name, item in account["domain"]["cohorts"].items()
               for key in ("mass_kg", "energy_j")]
    account_cases = {
        "nonfinite_volume": ([(("streams", 0, "volume_m2"), math.nan)], INVALID),
        "negative_volume": ([(("streams", 0, "volume_m2"), -1.0)], INVALID),
        "reversed_interval": ([(("interval_s",), [dt, 0.0])], INVALID),
        "unknown_field": ([(("extra",), 1)], INVALID),
        "outflow_outside_window": ([(("streams", 1, "temperature_k"), 1700.0)], WINDOW),
        "material_side_crossed": ([(("segments", "left", "mesh"), "material")], VOLUME),
        "side_inflow": ([(("streams", 1), {"segment": "left", "direction": "in", "volume_m2": 1.0,
                                           "source": "exterior-asthenosphere"})], SIDE_INFLOW),
        "missing_conduction_term": ([(("conduction_in_j", "top"), DELETE)], INVALID),
        "latent_heat_source": ([(("interior", "latent_j"), 1.0)], THERMAL),
        "heat_fraction_above_one": ([(("interior", "heat_fraction"), 1.5)], INVALID),
        "open_mechanical_ledger": ([(("interior", "gravity_work_j"), gravity*(1+1e-6))], LEDGER),
        "work_on_the_free_surface": ([(("boundary_work_in_j", "top"), 1.0)], LEDGER),
        "fixed_base_sweeping_volume": ([(("segments", "base", "swept_volume_m2"), 1.0)], VOLUME),
        "geometry_disagrees_with_fluxes": ([(("domain", "volume_end_m2"), start+1e3)], VOLUME),
        "potential_source_temperature": ([(("sources", "exterior-asthenosphere", "temperature_kind"), "potential")],
                                         POTENTIAL),
        "source_energy_off_state": ([(("sources", "exterior-asthenosphere", "energy_j"), stored*1.001)], SOURCE_STATE),
        "source_other_datum": ([(("sources", "exterior-asthenosphere", "datum_k"), 0.0)], DATUM),
        "cohort_other_datum": ([(("domain", "cohorts", "asthenosphere-initial", "datum_k"), 0.0)], DATUM),
        "source_not_asthenosphere": ([(("materials", "asthenosphere", "role"), "oceanic_crust")], NOT_ASTHENOSPHERE),
        "string_density": ([(("materials", "asthenosphere", "density_kg_m3"), "3300")], INVALID),
        "mixed_directions_on_base": ([(("streams", 0), {"segment": "base", "direction": "in", "volume_m2": 1.0,
                                                        "source": "exterior-asthenosphere"}),
                                      (("streams", 1, "segment"), "base")], INVALID),
        "doubled_start_inventory": (doubled, INVENTORY),
        "heat_through_insulating_side": ([(("conduction_in_j", "left"), 1e12)], THERMAL_BOUNDARY),
    }
    outcomes = {}
    for group, function, original, cases in (("prescription", resolved_prescription, config, prescription_cases),
                                             ("account", propose_interval, account, account_cases)):
        for name, (changes, code) in cases.items():
            item = mutated(original, *changes)
            before = copy.deepcopy(item)
            outcomes[group+":"+name] = {"expected": code, "got": refusal_code(function, item),
                                        "input_unchanged": item == before}
    case_checks = {
        "case:units": (UNIT, refusal_code(validate_case, mutated(spec, (("units", "temperature"), "degC")))),
        "case:retained_base_temperature": (RETAINED_MISMATCH, refusal_code(check_retained, mutated(
            spec, (("control_parameters", "configuration", "base_temperature_k"), 1340.0)), ret)),
        "case:julian_year_for_aspect_input": (UNIT, refusal_code(per_aspect_year, 0.0025, 365.25*86400.0)),
    }
    for name, (code, got) in case_checks.items():
        outcomes[name] = {"expected": code, "got": got, "input_unchanged": True}
    checks = {
        "valid_inputs_pass": resolved_prescription(config)["status"] == PRESCRIPTION_ONLY
                             and propose_interval(account)["status"] == PROPOSED,
        "every_refusal_has_its_code": all(row["expected"] == row["got"] for row in outcomes.values()),
        "refusals_leave_inputs_unchanged": all(row["input_unchanged"] for row in outcomes.values()),
    }
    return finish(checks, cases=len(outcomes), outcomes=outcomes)


def interfaces_control(spec, ret, deadline=None):
    """I07 prescription versus supplied-account diagnostics, endpoint binding, and the I05 open-base cohort interface."""
    check_deadline(deadline)
    par, cfg, side, dt = reference_numbers(spec)
    width, depth, datum, F = cfg["width_m"], cfg["base_depth_m"], cfg["datum_k"], Fraction
    rule = resolved_prescription(configuration(spec, ret))
    base, left, top = (rule["segments"][name] for name in ("base", "left", "top"))
    prescription_ok = (
        rule["status"] == PRESCRIPTION_ONLY and rule["stokes_solution"] is False
        and (base["normal"]["prescribed"], base["tangential"]["prescribed"]) == ("velocity", "traction")
        and (left["normal"]["prescribed"], left["tangential"]["prescribed"]) == ("velocity", "traction")
        and (top["normal"]["prescribed"], top["tangential"]["prescribed"]) == ("traction", "traction")
        and base["tangential"]["traction_pa"] == 0.0 and base["flow"] == "inflow"
        and base["temperature"]["type"] == "dirichlet" and base["temperature"]["value_k"] == cfg["base_temperature_k"]
        and base["composition"] == {"type": "fixed_on_inflow", "material": par["asthenosphere"]["name"],
                                    "raw_plastic_history": 0.0}
        and left["temperature"]["type"] == "insulating" and left["composition"]["type"] == "natural"
        and rule["pressure"]["normalisation"] == "none" and rule["pressure"]["nullspace"].startswith("none")
        and len(rule["solver_outputs_required"]) >= 5)
    account = box_account(spec, ret, width=width, depth=depth, dt=dt, parent="interfaces", side_velocity=side,
                          inflow_volume=-rule["segments"]["base"]["normal"]["outward_velocity_m_s"]*width*dt)
    proposal = propose_interval(account)
    end_mass, end_energy = end_state_of(account, proposal)
    end_volume = account["domain"]["volume_end_m2"]
    diagnosis = diagnose_endpoint(account, proposal, end_mass, end_energy, end_volume)
    wrong = dict(end_mass, **{"asthenosphere-initial": end_mass["asthenosphere-initial"]*(1+1e-9)})
    # A proposal is bound to its account by recomputation and full comparison, never by status, law or a claimed
    # digest: every case below keeps the proposal's status and law, and the edited delta comes with a matching end state.
    shift = 1e12
    bound = {
        "foreign_parent": (mutated(account, (("parent",), "another-column")), proposal, end_energy),
        "foreign_interval": (mutated(account, (("interval_s",), [dt, 2*dt])), proposal, end_energy),
        "account_edited_after_booking": (mutated(account, (("conduction_in_j", "top"),
                                                           2*account["conduction_in_j"]["top"])), proposal, end_energy),
        "edited_delta": (account, mutated(proposal, (("domain", "energy_j"), proposal["domain"]["energy_j"]+shift)),
                         end_energy+shift),
    }
    binding = {}
    for name, (item, booked, energy) in bound.items():
        before = copy.deepcopy((item, booked))
        binding[name] = {"got": refusal_code(diagnose_endpoint, item, booked, end_mass, energy, end_volume),
                         "input_unchanged": (item, booked) == before}
    strip, rev = par["strip"], par["reversed"]
    w0, lam0 = strip["reference_width_m"], strip["stretch_start"]
    h0 = cfg["lithosphere_thickness_m"]
    per_kg = F(par["asthenosphere"]["heat_capacity_j_kg_k"])*(F(cfg["base_temperature_k"])-F(datum))
    i05 = {}
    for label, z in (("mckenzie_base_at_lithosphere_base", h0), ("selected_base", depth)):
        lam1 = strip["stretch_extension"]
        face = strip_open_base(route="open_base", reference_width_m=w0, base_depth_m=z, lithosphere_thickness_m=h0,
                               stretch_start=lam0, stretch_end=lam1)
        strip_booking = strip_account(spec, ret, face, depth=z, dt=dt, parent="strip-"+label)
        prop = propose_interval(strip_booking)
        masses, energy = end_state_of(strip_booking, prop)
        lateral = mutated(strip_booking, (("conduction_in_j", "left"), 1e12))
        exact_volume = F(w0)*F(z)*(F(lam1)-F(lam0))
        low, high = face["placement"]["inflow_depth_range_m"]
        placed = F(face["placement"]["width_m"])*(F(high)-F(low))
        new = list(prop["domain"]["new_cohorts"].values())
        i05[label] = {
            "inflow_volume_closed_form": agree(face["base_flux"]["volume_m2"], exact_volume, exact_volume),
            "placement_holds_the_inflow": abs(placed-exact_volume) <= F(POLICY["oracle_relative"])*exact_volume,
            "lithosphere_inventory_untouched": prop["domain"]["cohorts"] == {},
            "one_new_asthenosphere_cohort": len(new) == 1 and new[0]["role"] == "asthenosphere"
                                            and new[0]["raw_plastic_history"] == 0.0
                                            and new[0]["entry_interval_s"] == [0.0, dt],
            "same_incoming_state_as_i07": len(new) == 1 and new[0]["temperature_k"] == base["temperature"]["value_k"]
                                          and agree(new[0]["energy_j"]/new[0]["mass_kg"], per_kg, per_kg),
            "endpoint_closes_on_the_grown_volume": diagnose_endpoint(strip_booking, prop, masses, energy,
                                                                     face["volume_end_m2"])["status"] == ENDPOINT_CLOSES,
            "start_volume_as_end_volume_refused": refusal_code(diagnose_endpoint, strip_booking, prop, masses, energy,
                                                               face["volume_start_m2"]) == ENDPOINT,
            "material_sides_book_no_lateral_heat":
                prop["thermal"]["boundary_conditions"]["left"] == prop["thermal"]["boundary_conditions"]["right"]
                == "no_lateral_conduction" and refusal_code(propose_interval, lateral) == THERMAL_BOUNDARY}
    squeeze = strip_open_base(route="open_base", reference_width_m=w0, base_depth_m=depth, lithosphere_thickness_m=h0,
                              stretch_start=lam0, stretch_end=strip["stretch_compression"])
    squeezed = propose_interval(strip_account(spec, ret, squeeze, depth=depth, dt=dt, parent="strip-compression",
                                              outgoing=rev["outgoing_temperature_k"],
                                              asthenosphere_state=(rev["cohort_mean_temperature_k"],
                                                                   rev["cohort_temperature_range_k"])))
    squeeze_volume = F(w0)*F(depth)*(F(lam0)-F(strip["stretch_compression"]))
    closed_code = refusal_code(strip_open_base, route="closed", reference_width_m=w0, base_depth_m=depth,
                               lithosphere_thickness_m=h0, stretch_start=lam0, stretch_end=strip["stretch_extension"])
    # The lithosphere base h0/lam must stay at or above the fixed base at both ends: equality is admitted, a base one
    # ulp shallower is refused, and so is the reviewed case (h0 = 100 km over z_b = 150 km at the window's 0.6).
    lam_c, lam_low = strip["stretch_compression"], spec["control_policy"]["stretch_window"][0]
    edge = h0/lam_c

    def guard(z, start, end):
        return refusal_code(strip_open_base, route="open_base", reference_width_m=w0, base_depth_m=z,
                            lithosphere_thickness_m=h0, stretch_start=start, stretch_end=end)

    strip_guard = {}
    for when, order in (("start", lambda lam: (lam, lam0)), ("end", lambda lam: (lam0, lam))):
        strip_guard[when] = {"equality_admitted": guard(edge, *order(lam_c)) is None,
                             "one_ulp_shallower_base_refused": guard(math.nextafter(edge, 0.0), *order(lam_c)) == NO_LAYER,
                             "reviewed_case_refused": guard(depth, *order(lam_low)) == NO_LAYER}
    checks = {
        "i07_prescription_complete_and_unsolved": prescription_ok,
        "supplied_accounts_are_not_a_solution": proposal["evidence"] == SUPPLIED_ONLY
                                                and proposal["stokes_solution"] is False,
        "supplied_endpoint_closes": diagnosis["status"] == ENDPOINT_CLOSES and diagnosis["stokes_solution"] is False,
        "inconsistent_endpoint_refused": refusal_code(diagnose_endpoint, account, proposal, wrong, end_energy,
                                                      end_volume) == ENDPOINT,
        "end_volume_mismatch_refused": refusal_code(diagnose_endpoint, account, proposal, end_mass, end_energy,
                                                    end_volume*(1+1e-9)) == ENDPOINT,
        "foreign_or_edited_proposals_refused": all(row["got"] == FOREIGN for row in binding.values()),
        "binding_refusals_leave_inputs_unchanged": all(row["input_unchanged"] for row in binding.values()),
        "i05_interfaces": all(all(row.values()) for row in i05.values()),
        "i05_compression_exports_actual_state": squeeze["base_flux"]["direction"] == "out"
                                                and agree(squeeze["base_flux"]["volume_m2"], squeeze_volume, squeeze_volume)
                                                and set(squeezed["domain"]["cohorts"]) == {"asthenosphere-initial"}
                                                and not squeezed["domain"]["new_cohorts"] and not squeezed["sources"],
        "i05_lithosphere_stays_above_the_base": all(all(row.values()) for row in strip_guard.values()),
        "closed_strip_route_refused": closed_code == CLOSED,
    }
    return finish(checks, manufactured=True, stokes_solution=False, i05=i05, strip_guard=strip_guard,
                  endpoint_binding=binding, endpoint_energy_residual_j=diagnosis["energy_residual_j"],
                  compression_outflow_volume_m2=squeeze["base_flux"]["volume_m2"])


def pure_shear_work_control(spec, ret, deadline=None):
    """One independent mechanical-work control: the exact Newtonian pure-shear box (analytical; no Stokes solve).

    The field is checked in exact arithmetic against incompressibility, the momentum balance, the stated stress and
    each selected boundary condition. Each boundary power comes from traction times velocity, the gravity power from
    the body force and the dissipation from stress times strain rate, each integrated on its own and compared with the
    stated closed forms. Only then, times dt, do they enter the tool's ledger, which must close and must refuse sign
    and double-count errors.
    """
    check_deadline(deadline)
    par, cfg, side, dt = reference_numbers(spec)
    F = Fraction
    field = PureShear(F(2*side/cfg["width_m"]), F(par["pure_shear"]["viscosity_pa_s"]),
                      F(par["asthenosphere"]["density_kg_m3"]), F(cfg["gravity_m_s2"]), F(cfg["width_m"]),
                      F(cfg["base_depth_m"]))
    a, eta, rho, g, W, H = field.a, field.eta, field.rho, field.g, field.width, field.height
    xs, ys = (-W/2, F(0), W/2), (F(0), H/2, H)
    nodes = [(x, y) for x in xs for y in ys]
    field_checks = {
        "divergence_free": all(field.strain_rate(x, y)[0]+field.strain_rate(x, y)[1] == 0 for x, y in nodes),
        "momentum_balance": all(field.momentum_residual(x, y) == (0, 0) for x, y in nodes),
        "stress_is_the_stated_stress": all(field.stress(x, y) == (4*eta*a-rho*g*(H-y), -rho*g*(H-y), 0)
                                           for x, y in nodes),
        "top_traction_free_and_stationary": all(field.stress(x, H)[1:] == (0, 0) and field.velocity(x, H)[1] == 0
                                                for x in xs),
        "no_tangential_traction_on_base_and_sides": all(field.stress(x, y)[2] == 0 for x, y in nodes),
        "prescribed_normal_velocities": all(field.velocity(W/2, y)[0] == -field.velocity(-W/2, y)[0] == a*W/2
                                            for y in ys) and all(field.velocity(x, F(0))[1] == a*H for x in xs),
    }
    powers = pure_shear_powers(field)
    stated = {"base": a*rho*g*W*H**2, "sides": 4*eta*a**2*W*H-a*rho*g*W*H**2/2, "gravity": -a*rho*g*W*H**2/2,
              "dissipation": 4*eta*a**2*W*H}
    power_checks = {
        "base_power_is_stated": powers["base"] == stated["base"],
        "side_power_is_stated": powers["left"]+powers["right"] == stated["sides"] and powers["left"] == powers["right"],
        "gravity_power_is_stated": powers["gravity"] == stated["gravity"],
        "dissipation_is_stated": powers["dissipation"] == stated["dissipation"],
        "top_does_no_work": powers["top"] == 0,
        "powers_balance_exactly": powers["base"]+powers["right"]+powers["top"]+powers["left"]+powers["gravity"]
                                  == powers["dissipation"],
        "inflow_is_the_reference_rule": agree(float(a*H), 2*F(side)*H/W, 2*F(side)*H/W),
    }
    account = pure_shear_account(spec, field, dt, powers, "pure-shear")
    proposal = propose_interval(account)
    work, step = account["boundary_work_in_j"], F(dt)
    sigma_base = float(field.stress(F(0), F(0))[1])            # n = (0, -1): the base normal stress is sigma_yy
    base_flux = -account["streams"][0]["volume_m2"]            # outward material flux through the fixed base
    corners = field.corners()
    viscous_free = {"right": traction_power(field.lithostatic_stress, field.velocity, corners[1], corners[2]),
                    "left": traction_power(field.lithostatic_stress, field.velocity, corners[3], corners[0])}
    errors = {
        "inward_normal": ([(("boundary_work_in_j", name), -work[name]) for name in ("base", "left", "right")], LEDGER),
        "base_compression_booked_as_tension": ([(("boundary_work_in_j", "base"), flow_work(-sigma_base, base_flux))],
                                               LEDGER),
        "gravity_reversed": ([(("interior", "gravity_work_j"), -account["interior"]["gravity_work_j"])], LEDGER),
        "base_flow_work_counted_twice": ([(("boundary_work_in_j", "base"),
                                           work["base"]+flow_work(sigma_base, base_flux))], LEDGER),
        "side_viscous_traction_omitted": ([(("boundary_work_in_j", name), float(power*step))
                                           for name, power in viscous_free.items()], LEDGER),
        "dissipation_omitted": ([(("interior", "dissipation_j"), 0.0)], LEDGER),
        "base_flow_work_booked_as_heat": ([(("interior", "boundary_work_j"), flow_work(sigma_base, base_flux))],
                                          THERMAL),
    }
    outcomes = {}
    for name, (changes, code) in errors.items():
        item = mutated(account, *changes)
        before = copy.deepcopy(item)
        outcomes[name] = {"expected": code, "got": refusal_code(propose_interval, item), "input_unchanged": item == before}
    base_work = powers["base"]*step
    checks = dict(field_checks, **power_checks,
                  flow_work_equals_base_traction_work=agree(flow_work(sigma_base, base_flux), base_work, base_work),
                  tool_ledger_closes_on_independent_terms=proposal["mechanical"]["status"] == "CLOSED",
                  sign_and_double_count_errors_refused=all(row["expected"] == row["got"] for row in outcomes.values()),
                  refused_inputs_unchanged=all(row["input_unchanged"] for row in outcomes.values()))
    return finish(checks, mechanical_terms="exact analytical pure shear of a homogeneous Newtonian box",
                  thermal_terms="declared isothermal state, not tested", numerical_solve=False,
                  strain_rate_s=float(a), viscosity_pa_s=float(eta),
                  powers_w_per_m={name: float(value) for name, value in powers.items()},
                  work_j={name: float(value*step) for name, value in powers.items()},
                  ledger_residual_j=proposal["mechanical"]["residual_j"], errors=outcomes)


CONTROLS = (("constant_volume", constant_volume_control), ("moving_surface", moving_surface_control),
            ("flow_direction", flow_direction_control), ("accounts", accounts_control),
            ("pure_shear_work", pure_shear_work_control), ("exhaustion", exhaustion_control),
            ("refusals", refusals_control), ("interfaces", interfaces_control))


# ----------------------------------------------------------------------------- evidence

def digest(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()


def bindings():
    return {name: digest(name) for name in NEW_FILES+RETAINED}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        result = dict(schema=EVIDENCE_SCHEMA, status="INCOMPLETE", scientific_acceptance=False, stokes_solution=False,
                      law=LAW, runtime=dict(python=platform.python_version(), system=platform.system(),
                                            machine=platform.machine()),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            result["source_sha256"] = before
            spec = load_case()
            ret = retained_inputs()
            check_retained(spec, ret)
            result["case"] = spec
            deadline = start+spec["control_policy"]["maximum_seconds"]     # cooperative budget, checked per control
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, ret, deadline)
                    check_deadline(deadline)                # an overrunning control is not recorded as a pass
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError, ArithmeticError, KeyError, TypeError) as exc:
                    result["controls"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                    error_type=type(exc).__name__,
                                                    error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
            result["source_unchanged"] = before == bindings()
            passed = (result["source_unchanged"] and len(result["controls"]) == len(CONTROLS)
                      and all(c["status"] == "PASS" for c in result["controls"].values()))
            result["status"] = PASS if passed else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        result["elapsed_seconds_after_imports"] = time.perf_counter()-start
        try:
            body = json.dumps(result, indent=2, allow_nan=False)
        except (TypeError, ValueError) as exc:          # never leave a partial record behind
            result = dict(schema=EVIDENCE_SCHEMA, status="FAIL", scientific_acceptance=False,
                          runtime=result["runtime"], error_type=type(exc).__name__,
                          error="evidence record not serialisable: "+str(exc)[:200], controls={},
                          elapsed_seconds_after_imports=result["elapsed_seconds_after_imports"])
            body = json.dumps(result, indent=2, allow_nan=False)
        stream.write(body+"\n")
    print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds_after_imports", "error")}
                     | {"controls": {k: c["status"] for k, c in result["controls"].items()}}))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
