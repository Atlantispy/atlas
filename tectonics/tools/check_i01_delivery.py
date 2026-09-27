"""I01 phase-selective melt delivery control; WORKING NON-CANON.

Reuses W08 thermodynamics and emplacement. This is a prescribed extraction
interface, not a melting-rate, permeability, focusing or compaction solver.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
from atlas_tectonics.magmatic_thermodynamics import (
    MagmaticThermodynamics, MagmaticThermalState, invert_enthalpy, reheat)
from atlas_tectonics.magmatic_emplacement import (
    MagmaticPayload, EmplacementTarget, emplace_magma, accounting_entries)
from atlas_tectonics.resources import WorkBudget, select_budget

POLICY = {"relative_tolerance": 1e-12, "max_components": 64,
          "max_cells": 64, "work_bytes": 131072}


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError("melt delivery cancelled; no result published")


def _fraction(value):
    if isinstance(value, (bool, str, bytes)):
        raise ValueError("fraction must be a finite number in [0,1]")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("fraction must be a finite number in [0,1]")
    return value


def _close(a, b):
    return abs(a-b) <= POLICY["relative_tolerance"] * max(abs(a), abs(b), 1e-300)


def _enthalpy(mass, temperature, fraction, law):
    cp = math.fsum(float(m)*float(c) for m, c in zip(mass, law.cp_j_kg_k))
    latent = math.fsum(float(m)*float(l) for m, l in zip(mass, law.latent_heat_j_kg))
    result = math.fsum((cp*(temperature-law.reference_temperature_k), latent*fraction))
    if not math.isfinite(result):
        raise ValueError("phase enthalpy outside finite range")
    return result


@dataclass(frozen=True)
class LiquidSplit:
    remaining: MagmaticThermalState
    liquid: MagmaticThermalState
    initial_enthalpy_j: float
    extraction_fraction: float


def extract_liquid(component_mass_kg, enthalpy_j, law, *,
                   fraction_of_available_liquid, budget=None, cancel=None):
    """Separate a declared fraction of CURRENT liquid, without adding heat.

    One finite common-Tm, congruent W08 node only. Per-component liquid mass is
    m_i*f*alpha; liquid carries cp_i*(T-Tref)+L_i, not the bulk specific enthalpy.
    The unextracted source, including retained liquid, is returned. Caller owns
    transport timing, physical extraction authority and atomic state replacement.
    """
    _cancel(cancel)
    alpha = _fraction(fraction_of_available_liquid)
    work = WorkBudget(POLICY["work_bytes"], parent=select_budget(budget))
    with work.reserve(32768, category="i01-phase-split"):
        original = invert_enthalpy(component_mass_kg, enthalpy_j, law,
                                   budget=work, cancel=cancel)
        if len(original.phase) != 1:
            raise ValueError("phase extraction requires exactly one source node")
        f, temperature = original.liquid_fraction[0], original.temperature_k[0]
        if original.phase == ("single_phase",):
            raise ValueError("zero-latent law does not establish liquid availability")
        mass = original.component_mass_kg[0]
        if f is None:  # The already validated empty state.
            f, temperature = 0.0, law.melting_temperature_k
        if alpha == 0 or f == 0:
            empty = invert_enthalpy([np.zeros_like(mass)], [0.], law,
                                    budget=work, cancel=cancel)
            return LiquidSplit(original, empty, float(original.enthalpy_j[0]), alpha)
        take = f*alpha
        if f and alpha and not take:
            raise ValueError("nonzero extraction fraction underflows")
        moved = mass*take
        remaining = mass-moved
        if np.any((mass > 0) & (take > 0) & (moved == 0)):
            raise ValueError("nonzero extracted component underflows")
        if np.any((moved > 0) & (remaining == mass)):
            raise ValueError("source debit is below component resolution")
        if take < 1 and np.any((mass > 0) & (remaining == 0)):
            raise ValueError("nonzero remaining component is unresolved")
        moved_h = _enthalpy(moved, temperature, 1.0, law)
        remaining_f = (f-take)/(1-take) if take < 1 else 0.0
        remaining_h = _enthalpy(remaining, temperature, remaining_f, law)
        initial_h = float(original.enthalpy_j[0])
        scale = max(abs(initial_h), abs(moved_h), abs(remaining_h), 1e-300)
        if abs(math.fsum((remaining_h, moved_h, -initial_h))) > POLICY["relative_tolerance"]*scale:
            raise ValueError("phase split enthalpy closure failed")
        residual = invert_enthalpy([remaining], [remaining_h], law, budget=work, cancel=cancel)
        liquid = invert_enthalpy([moved], [moved_h], law, budget=work, cancel=cancel)
        if liquid.mass_kg[0] and not _close(liquid.liquid_fraction[0], 1.0):
            raise ValueError("extracted liquid phase is numerically unresolved")
        _cancel(cancel)
        return LiquidSplit(residual, liquid, initial_h, alpha)


def place_liquid(split, target, *, source_id, transfer_id, liquid_density_kg_m3,
                 mode, budget=None, cancel=None):
    """Connect the split to existing finite W08 emplacement; no latent heat added.

    Output is hot emplaced material, NOT automatically solid crust. Native
    accounting_entries must be applied to the complete pending transaction set
    to reject duplicate transfer IDs. This pure function does not commit state.
    """
    _cancel(cancel)
    if type(split) is not LiquidSplit or type(target) is not EmplacementTarget:
        raise ValueError("typed phase split and target required")
    if len(target.column_ids) > POLICY["max_cells"]:
        raise ValueError("I01 delivery target exceeds 64-cell control bound")
    if mode not in ("underplating", "extrusive"):
        raise ValueError("I01 control requires explicit additive accommodation")
    if split.liquid.mass_kg[0] <= 0:
        raise ValueError("no liquid delivery; retain source and publish no emplacement")
    work = WorkBudget(POLICY["work_bytes"], parent=select_budget(budget))
    payload = MagmaticPayload(split.liquid.component_ids,
        split.liquid.component_mass_kg[0], float(split.liquid.enthalpy_j[0]),
        liquid_density_kg_m3, source_id=source_id, transfer_id=transfer_id,
        enthalpy_source=split.liquid.enthalpy_source_id, budget=work, cancel=cancel)
    return emplace_magma(payload, target, mode=mode, source_id=transfer_id,
                         budget=work, cancel=cancel)


def controls(spec):
    rows = []
    for case in spec["cases"]:
        law = MagmaticThermodynamics(tuple(case["components"]), case["cp_j_kg_k"],
            case["latent_j_kg"], melting_temperature_k=case["tm_k"],
            reference_temperature_k=case["tref_k"], source_id=case["name"],
            provenance="authored analytical phase-transfer control; not mantle calibration")
        mass = np.asarray(case["mass_kg"])
        h = _enthalpy(mass, case["temperature_k"], case["liquid_fraction"], law)
        start = time.perf_counter()
        split = extract_liquid([mass], [h], law,
                              fraction_of_available_liquid=case["extract_fraction"])
        elapsed = time.perf_counter()-start
        expected = math.fsum(case["mass_kg"])*case["liquid_fraction"]*case["extract_fraction"]
        actual = float(split.liquid.mass_kg[0])
        closure = math.fsum((float(split.remaining.enthalpy_j[0]),
                            float(split.liquid.enthalpy_j[0]), -h))
        rows.append(dict(name=case["name"], moved_mass_kg=actual,
            expected_mass_kg=expected, energy_residual_j=closure,
            passed=_close(actual, expected), phase_split_seconds=elapsed))
    # Known two-component liquid, split -> emplacement -> explicitly paid cooling.
    law = MagmaticThermodynamics(("a", "b"), [1000., 1500.], [400000., 600000.],
        melting_temperature_k=1500., reference_temperature_k=300.,
        source_id="delivery-loop", provenance="analytical synthetic control")
    mass = np.array([6000., 4000.])
    h = _enthalpy(mass, 1500., .2, law)
    split = extract_liquid([mass], [h], law, fraction_of_available_liquid=.5)
    target = EmplacementTarget(("left", "right"), [2., 3.], [2800., 3000.], [.25, .75],
        geometry_source="declared-new-area", frame_id="local", datum_id="reference", epoch_id="t1")
    result = place_liquid(split, target, source_id="mantle", transfer_id="delivery-1",
                         liquid_density_kg_m3=2700., mode="underplating")
    accounting_entries((result,))
    deposited = result.incoming_component_mass_kg
    # Target below Tm is allowed only by an explicit energy sink into surroundings.
    cold_h = np.array([_enthalpy(row, 1000., 0., law) for row in deposited])
    heat = cold_h-result.incoming[:, 1]
    cooled = reheat(deposited, result.incoming[:, 1], heat, law)
    released = -math.fsum(float(v) for v in heat)
    final_h = math.fsum(float(v) for v in cooled.state.enthalpy_j)
    balance = math.fsum((float(split.remaining.enthalpy_j[0]), final_h, released, -h))
    expected_dz = np.array([250/(2800*2), 750/(3000*3)])
    passed = all(r["passed"] for r in rows) and abs(balance) <= POLICY["relative_tolerance"]*abs(h)
    passed = passed and np.allclose(result.geometry[:, 0], expected_dz,
                                   rtol=POLICY["relative_tolerance"], atol=0)
    passed = passed and cooled.state.phase == ("solid", "solid")
    passed = passed and _close(released, 1080000000.)
    passed = passed and _close(float(split.remaining.mass_kg[0]), 9000.)
    passed = passed and _close(math.fsum(float(v) for v in result.incoming[:, 0]), 1000.)
    return dict(passed=bool(passed), cases=rows, connected_w08=dict(
        delivered_mass_kg=float(split.liquid.mass_kg[0]),
        source_remaining_mass_kg=float(split.remaining.mass_kg[0]),
        deposited_thickness_m=result.geometry[:, 0].tolist(),
        released_heat_j=released, expected_released_heat_j=1080000000.,
        total_energy_residual_j=balance, final_phase=list(cooled.state.phase)))


def source_binding():
    names = ["tools/check_i01_delivery.py", "tests/test_i01_delivery.py",
             "cases/i01_delivery_v1.json", "docs/I01_DELIVERY.md"]
    # Normal package imports execute __init__, so bind the full unchanged native
    # source tree rather than pretending only the two directly used files matter.
    names += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/"src/atlas_tectonics").rglob("*.py"))]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        start = time.perf_counter()
        report = dict(schema="atlas.i01-delivery-control.v1", status="INCOMPLETE",
            scientific_acceptance=False, runtime=dict(python=platform.python_version(),
            numpy=np.__version__, system=platform.system(), machine=platform.machine()))
        try:
            report["source_sha256"] = source_binding()
            spec = json.loads((ROOT/"cases/i01_delivery_v1.json").read_text(encoding="utf-8"))
            if spec["policy"] != POLICY:
                raise ValueError("case policy differs from executable")
            report.update(controls(spec))
            report["source_unchanged"] = report["source_sha256"] == source_binding()
            report["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if report["passed"] and report["source_unchanged"] else "FAIL"
        except Exception as exc:
            report.update(status="FAIL", error_type=type(exc).__name__)
        report["elapsed_seconds"] = time.perf_counter()-start
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "elapsed_seconds")}))
    return 0 if report["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
