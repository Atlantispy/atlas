"""Discharge-responsive extension of the pinned m=.5, n=1 area-law reference.

E = K_A sqrt(Q / R_ref) S, where K_A is calibrated at a declared uniform
runoff R_ref [m/year]. Q [m3/year] / R_ref is an equivalent area [m2], so K_A
retains 1/year units. Equivalently K_Q = K_A / sqrt(R_ref) has units
m**(-1/2) year**(-1/2). No default rainfall, runoff or calibration is invented.
This is a reduced long-term discharge law, not storm hydraulics or empirical
acceptance. The unchanged area law remains available only as historical reference.
"""
from __future__ import annotations

import ast
import hashlib
import math
from pathlib import Path
import sys
import types
import uuid

CORE_PATH = Path(__file__).resolve().parents[1] / "terrain_model_r2_repair_r1/core.py"
CORE_SHA256 = "b91a65135aaa49e67da5c26388d0d72142d32ee1229ec5d2e5da405b8c16fb45"


def real(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ValueError(name + " requires a finite real quantity, not a score/object")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(name + " is outside binary64 range") from exc
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(name + " outside supported range")
    return value


def runoff_normalised_intensity(discharge_m3_year, slope, reference_runoff_m_year):
    q = real(discharge_m3_year, "discharge_m3_year")
    s = real(slope, "slope")
    ref = real(reference_runoff_m_year, "reference_runoff_m_year", positive=True)
    if q == 0 or s == 0:
        return 0.0
    # Keep binary exponents separate: even sqrt(Q)/sqrt(R_ref) can overflow
    # before multiplication by a tiny slope, despite a representable result.
    mq, eq = math.frexp(q)
    mr, er = math.frexp(ref)
    ms, es = math.frexp(s)
    exponent, odd = divmod(eq-er, 2)
    mantissa = math.sqrt(mq/mr) * ms * (math.sqrt(2.) if odd else 1.)
    try:
        answer = math.ldexp(mantissa, exponent+es)
    except OverflowError as exc:
        raise ValueError("discharge intensity is not representable") from exc
    if not math.isfinite(answer) or answer == 0:
        raise ValueError("discharge intensity is not representable")
    return answer


def bound_core():
    """Return a private module compiled from checked bytes, never a stale alias."""
    raw = CORE_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORE_SHA256:
        raise ValueError("pinned repaired R2 core changed")
    name = "_scientific_r1_core_" + uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(CORE_PATH)
    # dataclasses resolves annotations through this private identity while loading.
    sys.modules[name] = module
    try:
        exec(compile(raw, str(CORE_PATH), "exec", dont_inherit=True), module.__dict__)
    finally:
        del sys.modules[name]
    return module


def channel_step(core, state, runoff_m_year, sediment_k_per_year, rock_k_per_year,
                 cover_scale_m, settling_m_year, dt_years, external_outlets, *,
                 reference_runoff_m_year, calibration_evidence):
    """Execute the actual R2 channel algorithm with one explicit forcing change.

    A fresh private pinned core supplies state validation and drainage/accounting.
    Caller states are rebuilt into it; the caller's module globals are never used
    for numerical execution. The adapter changes the single reviewed expression,
    not the copied tests or the original reference. The core argument is kept for
    ergonomic construction of the returned state, not trusted as executable input.
    """
    ref = real(reference_runoff_m_year, "reference runoff", positive=True)
    if not isinstance(calibration_evidence, str) or not calibration_evidence.strip():
        raise ValueError("explicit coefficient/reference-runoff evidence required")
    pinned = bound_core()
    grid = pinned.Grid(**vars(state.grid))
    source = pinned.State(grid, state.bedrock_m, state.mobile_solid_m3, state.porosity,
                          state.rock_density_kg_m3, state.sediment_density_kg_m3,
                          state.source_status)
    raw = CORE_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORE_SHA256:
        raise ValueError("pinned repaired R2 core changed during binding")
    tree = ast.parse(raw)
    original = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "channel_step")
    matches = []
    for node in ast.walk(original):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "intensity" for t in node.targets):
            matches.append(node)
    expected = ast.parse("math.sqrt(area[i])*slope", mode="eval").body
    if len(matches) != 1 or ast.dump(matches[0].value) != ast.dump(expected):
        raise ValueError("reviewed channel forcing expression no longer matches")
    matches[0].value = ast.parse("_forcing(water[i], slope, _reference_runoff)", mode="eval").body
    patched = ast.fix_missing_locations(ast.Module(body=[original], type_ignores=[]))
    namespace = dict(pinned.__dict__, _forcing=runoff_normalised_intensity, _reference_runoff=ref)
    exec(compile(patched, str(Path(__file__)), "exec", dont_inherit=True), namespace)
    result, receipt = namespace["channel_step"](
        source, runoff_m_year, sediment_k_per_year, rock_k_per_year, cover_scale_m,
        settling_m_year, dt_years, external_outlets)
    receipt.update(erosion_law="runoff_normalised_m_half_n_one",
                   reference_runoff_m_year=ref, coefficient_units="1/year at declared reference runoff",
                   calibration_evidence=calibration_evidence,
                   predecessor_core_sha256=CORE_SHA256, physical_validation="NOT_EMPIRICALLY_ACCEPTED")
    return result, receipt
