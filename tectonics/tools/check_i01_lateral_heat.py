"""Conditional lateral-conduction omission bound; WORKING NON-CANON.

Only the declared semi-discrete thermal model is certified. No neck evolution,
mechanical feedback, continuum error or separation claim is implemented.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import platform
import time

ROOT = Path(__file__).resolve().parents[1]
POLICY = {"max_cells": 256, "max_contacts": 1024, "max_windows": 64,
          "input_bits": 4096, "oracle_relative": 1e-12}
ASSUMPTIONS = {
    "geometry": "fixed_orthogonal_control_volumes",
    "thermal_properties": "prescribed_temperature_independent",
    "forcing": "identical_prescribed_sources_and_vertical_boundaries",
    "lateral_boundaries": "closed",
    "vertical_operator": "nonnegative_offdiagonals_nonpositive_row_sums",
    "feedback": "none",
    "claim": "semidiscrete_temperature_only",
}


def rational(value, name, *, positive=False):
    if type(value) not in (int, float, Fraction):
        raise ValueError(name+": finite real number required")
    if type(value) is float and not math.isfinite(value):
        raise ValueError(name+": finite real number required")
    out = Fraction(value)
    if out < 0 or (positive and out == 0):
        raise ValueError(name+": outside nonnegative/positive support")
    if max(abs(out.numerator).bit_length(), out.denominator.bit_length()) > POLICY["input_bits"]:
        raise ValueError(name+": input precision budget exceeded")
    return out


def upper_float(value):
    try:
        out = float(value)
    except OverflowError as exc:
        raise ValueError("display bound is not representable") from exc
    if not math.isfinite(out):
        raise ValueError("display bound is not representable")
    if Fraction(out) < value:
        out = math.nextafter(out, math.inf)
    if not math.isfinite(out):
        raise ValueError("display bound is not representable")
    return out


@dataclass(frozen=True, init=False)
class Network:
    """Immutable capacities and paired contacts; construction does not prove geometry."""
    capacities: tuple
    contacts: tuple

    def __init__(self, capacities_j_k, contacts, *, assumptions):
        if type(assumptions) is not dict or assumptions != ASSUMPTIONS:
            raise ValueError("unsupported geometry, forcing, operator or coupled-feedback claim")
        if type(capacities_j_k) is not list or not 1 <= len(capacities_j_k) <= POLICY["max_cells"]:
            raise ValueError("a bounded nonempty capacity list is required")
        capacities = tuple(rational(c, "heat capacity", positive=True) for c in capacities_j_k)
        if type(contacts) is not list or len(contacts) > POLICY["max_contacts"]:
            raise ValueError("bounded contact list required")
        pairs, prepared = set(), []
        keys = {"left", "right", "conductivity_w_m_k", "area_m2", "distance_m"}
        for item in contacts:
            if type(item) is not dict or set(item) != keys:
                raise ValueError("contact fields must declare exactly endpoints, k, area and distance")
            i, j = item["left"], item["right"]
            if any(type(v) is not int or not 0 <= v < len(capacities) for v in (i, j)) or i == j:
                raise ValueError("distinct valid integer contact endpoints required")
            pair = tuple(sorted((i, j)))
            if pair in pairs:
                raise ValueError("duplicate or reversed duplicate contact")
            pairs.add(pair)
            k = rational(item["conductivity_w_m_k"], "conductivity", positive=True)
            area = rational(item["area_m2"], "area", positive=True)
            distance = rational(item["distance_m"], "distance", positive=True)
            prepared.append((i, j, k*area/distance))
        object.__setattr__(self, "capacities", capacities)
        object.__setattr__(self, "contacts", tuple(prepared))

    def residual_bound(self, differences_k):
        """max_i sum_j G_ij Delta_ij/C_i, in K/s; linear graph storage/work."""
        if type(differences_k) is not list or len(differences_k) != len(self.contacts):
            raise ValueError("one whole-window difference bound per declared contact required")
        heat = [Fraction(0) for _ in self.capacities]
        for (i, j, conductance), difference in zip(self.contacts, differences_k):
            flow = conductance*rational(difference, "temperature difference bound")
            heat[i] += flow
            heat[j] += flow
        return max(q/c for q, c in zip(heat, self.capacities))


def admission(network, windows, *, temperature_allowance_k, initial_error_bound_k=0):
    """Conditional whole-window bound, never inferred from endpoint or interior samples.

    Each envelope constrains the exact column-only thermal trajectory. The initial
    error can carry the previous window's bound; it is not reset by a new call.
    """
    if type(network) is not Network:
        raise ValueError("a prepared Network is required")
    allowance = rational(temperature_allowance_k, "temperature allowance")
    error = rational(initial_error_bound_k, "initial error bound")
    if type(windows) is not list or not 1 <= len(windows) <= POLICY["max_windows"]:
        raise ValueError("a bounded nonempty window list is required")
    result = dict(conditional_temperature_admissible=False, coupled_neck_certified=False,
                  physical_separation_authorised=False, continuum_error_certified=False,
                  status="REFUSED_UNCERTIFIED_ENVELOPE")
    duration, increments = Fraction(0), []
    for window in windows:
        if type(window) is not dict or set(window) != {"duration_s", "envelope"}:
            raise ValueError("each window requires duration_s and envelope only")
        dt = rational(window["duration_s"], "duration", positive=True)
        envelope = window["envelope"]
        if (type(envelope) is not dict or envelope.get("kind") != "declared_whole_window"):
            return result
        if set(envelope) != {"kind", "difference_bounds_k", "basis"}:
            raise ValueError("whole-window envelope requires bounds and their declared basis")
        if type(envelope["basis"]) is not str or not envelope["basis"].strip():
            raise ValueError("a nonempty envelope basis is required")
        increment = dt*network.residual_bound(envelope["difference_bounds_k"])
        error += increment
        duration += dt
        increments.append(str(increment))
    passed = error <= allowance
    result.update(status="PASS_CONDITIONAL_THERMAL_BOUND" if passed else "REFUSED_TEMPERATURE_BUDGET",
                  conditional_temperature_admissible=passed,
                  error_bound_k=upper_float(error), error_bound_exact_k=str(error),
                  temperature_allowance_exact_k=str(allowance), duration_exact_s=str(duration),
                  window_increments_exact_k=increments, windows=len(windows),
                  cells=len(network.capacities), contacts=len(network.contacts))
    return result


def source_binding():
    names = ["tools/check_i01_lateral_heat.py", "tests/test_i01_lateral_heat.py",
             "cases/i01_lateral_heat_v1.json", "docs/I01_LATERAL_HEAT.md"]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def controls(spec):
    if (type(spec) is not dict or set(spec) != {"schema", "policy", "assumptions", "two_cell"}
            or spec["schema"] != "atlas.i01-lateral-heat-case.v1" or spec["policy"] != POLICY):
        raise ValueError("case schema/fields/policy differs from executable")
    case = spec["two_cell"]
    if set(case) != {"capacities_j_k", "contacts", "initial_difference_k", "duration_s",
                     "permissive_allowance_k", "strict_allowance_k"}:
        raise ValueError("two-cell case fields differ from the frozen control")
    network = Network(case["capacities_j_k"], case["contacts"], assumptions=spec["assumptions"])
    if len(network.capacities) != 2 or len(network.contacts) != 1:
        raise ValueError("the analytical control requires two cells and one contact")
    delta = rational(case["initial_difference_k"], "initial difference", positive=True)
    dt = rational(case["duration_s"], "duration", positive=True)
    window = {"duration_s": dt, "envelope": {"kind": "declared_whole_window",
              "difference_bounds_k": [delta], "basis": "No vertical exchange or sources: reduced cells remain constant."}}
    loose = admission(network, [window], temperature_allowance_k=case["permissive_allowance_k"])
    strict = admission(network, [window], temperature_allowance_k=case["strict_allowance_k"])
    i, j, g = network.contacts[0]
    ci, cj = network.capacities[i], network.capacities[j]
    beta_t = g*(1/ci+1/cj)*dt
    fraction = -math.expm1(-float(beta_t))
    # Independent closed form, not used in the exact admission comparison.
    di = -float(delta*cj/(ci+cj))*fraction
    dj = float(delta*ci/(ci+cj))*fraction
    measured = max(abs(di), abs(dj))
    conservation = abs(float(ci)*di+float(cj)*dj)
    energy_scale = max(1., abs(float(ci)*di), abs(float(cj)*dj))
    bound = Fraction(loose["error_bound_exact_k"])
    checks = {
        "permissive_admitted": loose["conditional_temperature_admissible"],
        "strict_refused": not strict["conditional_temperature_admissible"],
        "analytical_error_within_bound": measured <= upper_float(bound),
        "analytical_heat_conserved": conservation <= POLICY["oracle_relative"]*energy_scale,
        "no_coupled_claim": not loose["coupled_neck_certified"],
    }
    uniform = dict(window, envelope=dict(window["envelope"], difference_bounds_k=[0]))
    checks["uniform_zero"] = admission(network, [uniform], temperature_allowance_k=0)["error_bound_exact_k"] == "0"
    empty = Network([1, 3], [], assumptions=spec["assumptions"])
    no_edges = dict(window, envelope=dict(window["envelope"], difference_bounds_k=[]))
    checks["no_edges_zero"] = admission(empty, [no_edges], temperature_allowance_k=0)["error_bound_exact_k"] == "0"
    checks["cumulative_budget"] = not admission(network, [window, window],
                                               temperature_allowance_k=3*bound/2)["conditional_temperature_admissible"]
    # Endpoint equality cannot certify the interior of a prescribed pulse.
    for kind in ("samples_only", "unknown"):
        bad = dict(window, envelope=dict(window["envelope"], kind=kind))
        checks[kind+"_refused"] = not admission(network, [bad], temperature_allowance_k=1000)["conditional_temperature_admissible"]
    return dict(passed=all(checks.values()), checks=checks, permissive=loose, strict=strict,
                analytical_temperature_error_k=measured, analytical_heat_residual_j=conservation,
                scope="conditional semi-discrete thermal bound; analytical fixture only")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        started = time.perf_counter()
        result = dict(schema="atlas.i01-lateral-heat-control.v1", status="INCOMPLETE",
                      scientific_acceptance=False, coupled_neck_certified=False,
                      runtime={"python": platform.python_version(), "system": platform.system(),
                               "machine": platform.machine()})
        try:
            result["source_sha256"] = source_binding()
            spec = json.loads((ROOT/"cases/i01_lateral_heat_v1.json").read_text(encoding="utf-8"))
            result.update(controls(spec))
            result["source_unchanged"] = result["source_sha256"] == source_binding()
            result["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if result["passed"] and result["source_unchanged"] else "FAIL"
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__,
                          error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
        result["elapsed_seconds"] = time.perf_counter()-started
        json.dump(result, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({k: result[k] for k in ("status", "elapsed_seconds")}))
    return 0 if result["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
