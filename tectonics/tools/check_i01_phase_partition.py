"""Composition-aware I01 phase partition; WORKING NON-CANON.

Independent implementation of the fixed-P,T lever constraints in Keller & Katz
(2016), equations 4-7. No caloric law, reaction rate or native delivery is implied.
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
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
POLICY = dict(max_components=64, max_iterations=96, fraction_tolerance=1e-12,
              coefficient_min=1e-12, coefficient_max=1e12, benchmark_calls=200,
              benchmark_repetitions=3)


def number(value, name, *, positive=False):
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(name + " must be numeric")
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(name + " outside finite support")
    return value


def check(cancel, deadline):
    if cancel is not None and cancel.is_set():
        raise CancelledError("phase partition cancelled; no state committed")
    if deadline is not None and time.perf_counter() >= number(deadline, "deadline"):
        raise TimeoutError("phase partition deadline reached")


@dataclass(frozen=True, slots=True)
class Partition:
    """Supplied solid/liquid concentration ratios at ONE pressure/temperature.

    Coefficients are a physical input, not fitted to the requested melt fraction.
    This object cannot update temperature or pressure or determine enthalpy.
    """
    component_ids: tuple
    coefficients: tuple
    pressure_pa: float
    temperature_k: float
    source_id: str

    def __post_init__(self):
        ids = self.component_ids
        if (type(ids) is not tuple or not 1 <= len(ids) <= POLICY["max_components"]
                or any(type(x) is not str or not x or len(x) > 128 for x in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("unique bounded component IDs required")
        if type(self.coefficients) is not tuple or len(self.coefficients) != len(ids):
            raise ValueError("one immutable partition coefficient per component")
        k = tuple(number(x, "partition coefficient", positive=True) for x in self.coefficients)
        if any(not POLICY["coefficient_min"] <= x <= POLICY["coefficient_max"] for x in k):
            raise ValueError("partition coefficient outside represented support")
        p = number(self.pressure_pa, "pressure")
        t = number(self.temperature_k, "temperature", positive=True)
        if p < 0 or type(self.source_id) is not str or not self.source_id or len(self.source_id) > 256:
            raise ValueError("nonnegative pressure and bounded source identity required")
        object.__setattr__(self, "coefficients", k)
        object.__setattr__(self, "pressure_pa", p)
        object.__setattr__(self, "temperature_k", t)


@dataclass(frozen=True, slots=True)
class Phases:
    partition: Partition
    solid_mass_kg: tuple
    liquid_mass_kg: tuple
    iterations: int

    @property
    def liquid_fraction(self):
        mass = math.fsum((*self.solid_mass_kg, *self.liquid_mass_kg))
        return math.fsum(self.liquid_mass_kg)/mass if mass else None


def masses(values, count):
    if type(values) not in (tuple, list) or len(values) != count:
        raise ValueError("one component mass required in declared order")
    result = tuple(number(v, "mass") for v in values)
    if any(v < 0 for v in result):
        raise ValueError("negative component mass")
    total = math.fsum(result)
    if not math.isfinite(total):
        raise ValueError("unrepresentable total mass")
    return result, total


def _solve(partition, component_mass_kg, *, newton, cancel=None, deadline=None):
    check(cancel, deadline)
    if type(partition) is not Partition:
        raise ValueError("explicit fixed-state Partition required")
    mass, total = masses(component_mass_kg, len(partition.component_ids))
    if not total:
        return Phases(partition, mass, mass, 0)
    b = tuple(v/total for v in mass)
    if any(m > 0 and c == 0 for m, c in zip(mass, b)):
        raise ValueError("component fraction underflows")
    k = partition.coefficients
    if all(c == 0 or ki == 1 for c, ki in zip(b, k)):
        raise ValueError("phase fraction indeterminate: enthalpy or phase history required")

    def residual(f):
        terms = tuple((1-ki)/(f+(1-f)*ki) for ki in k)
        return (math.fsum(c*x for c, x in zip(b, terms)),
                -math.fsum(c*x*x for c, x in zip(b, terms)),
                16*sys.float_info.epsilon*math.fsum(abs(c*x) for c, x in zip(b, terms)))

    r0, _, _ = residual(0.)
    r1, _, _ = residual(1.)
    iterations = 0
    if r0 <= 0:
        f = 0.
    elif r1 >= 0:
        f = 1.
    else:
        lo, hi, f = 0., 1., .5
        for iterations in range(1, POLICY["max_iterations"]+1):
            check(cancel, deadline)
            r, slope, roundoff = residual(f)
            if roundoff > -slope*POLICY["fraction_tolerance"]:
                raise ValueError("phase fraction ill-conditioned at represented precision")
            # Bound the root correction with the minimum derivative magnitude
            # over the bracket, not a residual alone on a nearly flat curve.
            minimum_slope = math.fsum(c*((1-ki)/max(lo+(1-lo)*ki, hi+(1-hi)*ki))**2
                                      for c, ki in zip(b, k))
            if abs(r)+roundoff <= minimum_slope*POLICY["fraction_tolerance"]:
                break
            if r > 0:
                lo = f
            else:
                hi = f
            trial = f-r/slope if newton and slope < 0 else math.nan
            # Retain guaranteed bracket contraction, even for near-endpoint roots.
            f = trial if lo+.05*(hi-lo) < trial < hi-.05*(hi-lo) else (lo+hi)/2
        else:
            raise ValueError("phase partition iteration budget exhausted")
    # Evaluate the smaller inventory directly for EACH component. Subtracting
    # near-total liquid from bulk destroys the composition of a vanishing solid;
    # global phase size alone is insufficient when partition coefficients differ.
    solid, liquid = [], []
    for m, ki in zip(mass, k):
        solid_share = (1-f)*ki
        denominator = f+solid_share
        if f <= solid_share:
            l = m*(f/denominator)
            s = m-l
        else:
            s = m*(solid_share/denominator)
            l = m-s
        if m and 0 < f < 1 and (s == 0 or l == 0):
            raise ValueError("component phase inventory underflows")
        solid.append(s)
        liquid.append(l)
    solid, liquid = tuple(solid), tuple(liquid)
    if any(s < 0 or l < 0 or not math.isfinite(s+l) for s, l in zip(solid, liquid)):
        raise ValueError("unrepresentable phase inventory")
    if 0 < f < 1:
        cl = tuple(c/(f+(1-f)*ki) for c, ki in zip(b, k))
        cs = tuple(ki*x for ki, x in zip(k, cl))
        if max(abs(math.fsum(cl)-1), abs(math.fsum(cs)-1)) > POLICY["fraction_tolerance"]*2:
            raise ValueError("phase composition closure failed")
    check(cancel, deadline)
    return Phases(partition, solid, liquid, iterations)


def equilibrate(partition, component_mass_kg, *, cancel=None, deadline=None):
    """Return fixed-P,T equilibrium inventory; never alters a supplied state."""
    return _solve(partition, component_mass_kg, newton=True, cancel=cancel, deadline=deadline)


def extract(state, fraction, *, cancel=None, deadline=None):
    """Prescribed phase-selective MASS split, not an energy-bearing delivery.

    Return (residual phases, extracted component masses). Actual heat, reaction,
    timing and emplacement require the still-missing shared caloric provider.
    """
    check(cancel, deadline)
    alpha = number(fraction, "extraction fraction")
    if not 0 <= alpha <= 1 or type(state) is not Phases or type(state.partition) is not Partition:
        raise ValueError("typed phases and extraction fraction in [0,1] required")
    solid, _ = masses(state.solid_mass_kg, len(state.partition.component_ids))
    liquid, _ = masses(state.liquid_mass_kg, len(state.partition.component_ids))
    take = tuple(alpha*x for x in liquid)
    remain = tuple(x-y for x, y in zip(liquid, take))
    if any((x > 0 and alpha > 0 and y == 0)
           or (y > 0 and z == x) or (x > 0 and alpha < 1 and z == 0)
           for x, y, z in zip(liquid, take, remain)):
        raise ValueError("phase debit below numerical resolution")
    check(cancel, deadline)
    return Phases(state.partition, solid, remain, 0), take


def campaign(spec):
    partition = Partition(**{**spec["partition"],
        "component_ids": tuple(spec["partition"]["component_ids"]),
        "coefficients": tuple(spec["partition"]["coefficients"])})
    mass = spec["component_mass_kg"]
    initial = equilibrate(partition, mass)
    residual, taken = extract(initial, spec["extraction_fraction"])
    remaining = tuple(s+l for s, l in zip(residual.solid_mass_kg, residual.liquid_mass_kg))
    repeated = equilibrate(partition, remaining)
    leak = max(abs(a-b) for a, b in zip(residual.liquid_mass_kg, repeated.liquid_mass_kg))
    # Same input/physics/tolerance. Bisection is a diagnostic baseline, not API.
    samples = {"newton": [], "bisection": []}
    answers = {}
    for _ in range(POLICY["benchmark_repetitions"]):
        for name in samples:
            start = time.perf_counter()
            for _ in range(POLICY["benchmark_calls"]):
                answers[name] = _solve(partition, spec["benchmark_mass_kg"], newton=name == "newton")
            samples[name].append(time.perf_counter()-start)
    fast, slow = (statistics.median(samples[k]) for k in ("newton", "bisection"))
    parity = max(abs(a-b) for a, b in zip(answers["newton"].liquid_mass_kg, answers["bisection"].liquid_mass_kg))
    closure = max(abs(m-s-l-x) for m, s, l, x in zip(mass,
        residual.solid_mass_kg, residual.liquid_mass_kg, taken))
    passed = (abs(initial.liquid_fraction-spec["expected_fraction"]) < 1e-12
              and abs(math.fsum(taken)-spec["expected_extracted_kg"]) < 1e-8
              and leak < 1e-8 and closure < 1e-8 and parity < 1e-8)
    return dict(passed=passed, initial_liquid_fraction=initial.liquid_fraction,
        extracted_kg=math.fsum(taken), remaining_kg=math.fsum(remaining),
        remaining_liquid_kg=math.fsum(residual.liquid_mass_kg),
        repeated_equilibrium_liquid_kg=math.fsum(repeated.liquid_mass_kg),
        maximum_component_mass_residual_kg=closure, restart_difference_kg=leak,
        benchmark=dict(samples_seconds=samples, calls=POLICY["benchmark_calls"],
            newton_seconds=fast, bisection_seconds=slow, saved_seconds=slow-fast,
            saved_percent=100*(slow-fast)/slow, parity_kg=parity,
            iterations={k:v.iterations for k,v in answers.items()}),
        energy_delivery_authorised=False)


def bindings():
    names = ("tools/check_i01_phase_partition.py", "tests/test_i01_phase_partition.py",
             "docs/I01_PHASE_PARTITION.md", "cases/i01_phase_partition_v1.json")
    return {"tectonics/"+p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as out:
        report = dict(schema="atlas.i01-phase-partition-evidence.v1", status="FAIL",
                      runtime=dict(python=platform.python_version(), platform=platform.system()))
        start = time.perf_counter()
        try:
            report["source_sha256"] = bindings()
            spec = json.loads((ROOT/"cases/i01_phase_partition_v1.json").read_text(encoding="utf-8"))
            if spec["policy"] != POLICY:
                raise ValueError("case/executable policy differs")
            report.update(campaign(spec))
            report["source_unchanged"] = report["source_sha256"] == bindings()
            if report["passed"] and report["source_unchanged"]:
                report["status"] = "PASS_BOUNDED_PHASE_PARTITION_ONLY"
        except Exception as exc:
            report.update(error_type=type(exc).__name__, error=str(exc))
        report["elapsed_seconds"] = time.perf_counter()-start
        json.dump(report, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "elapsed_seconds")}))
    return 0 if report["status"] == "PASS_BOUNDED_PHASE_PARTITION_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
