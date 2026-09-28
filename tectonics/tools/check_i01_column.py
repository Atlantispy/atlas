"""I01 nonlinear constitutive/column controls, WORKING NON-CANON.

Prescribed pressure/temperature snapshots; no momentum, rupture or heat evolution.
I02.2a: the kernel is owned by atlas_tectonics._integration_column. This tool re-exports
those same objects and keeps the laboratory conversion, campaign, bindings and CLI.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np

from atlas_tectonics import _integration_column
# The package-owned kernel, re-exported: these are the same objects, not copies.
from atlas_tectonics._integration_column import R, POLICY, number, check_cancel, Creep, LocalLaw, Column

ROOT = Path(__file__).resolve().parents[1]


def laboratory_prefactor(a, n, *, stress_unit_pa, grain_exponent=0., grain_unit_m=1.):
    """Axial lab rate/differential stress -> tensor invariants, SI units.

    Only use for that declared laboratory convention, never on ASPECT's already
    converted coefficients. A_II=3**((n+1)/2)/2*A_lab*S**(-n)*L**m.
    """
    a = number(a, "lab prefactor", positive=True)
    n = number(n, "stress exponent", positive=True)
    s = number(stress_unit_pa, "stress unit", positive=True)
    d = number(grain_unit_m, "grain unit", positive=True)
    m = number(grain_exponent, "grain exponent", nonnegative=True)
    out = math.exp(math.log(a)+(n+1)/2*math.log(3)-math.log(2)-n*math.log(s)+m*math.log(d))
    return number(out, "converted prefactor", positive=True)


def campaign(spec):
    rate = spec["axial_rate_s"]
    coarse, fine = Column(spec["layers"], 64), Column(spec["layers"], 128)
    start = time.perf_counter()
    a, b = coarse.solve(rate), fine.solve(rate)
    solve_s = time.perf_counter()-start
    relative = abs(a["force_n_m"]-b["force_n_m"])/abs(b["force_n_m"])
    warm_layers = json.loads(json.dumps(spec["layers"]))
    for layer in warm_layers:
        layer["temperature_k"] = [t+100. for t in layer["temperature_k"]]
    warm = Column(warm_layers, 128).solve(rate)
    faster = fine.solve(10*rate)
    # Identical prepared coefficients/nodes/tolerances; compare only root algorithm.
    sample = LocalLaw.prepare((Creep(1e-25, 1., 0.), Creep(1e-40, 3.5, 0.)),
        1000., 1e8, grain_m=.001, cohesion_pa=1e6, friction_rad=.5,
        pore_pressure_pa=0., plastic_viscosity_pa_s=1e21)
    observed = {}
    for method in ("bisection", "newton"):
        start = time.perf_counter()
        answers = [sample.solve(rate*(1+i/10), method=method)
                   for i in range(POLICY["benchmark_repetitions"])]
        observed[method] = dict(seconds=time.perf_counter()-start,
            stresses=[r["stress_pa"] for r in answers], iterations=sum(r["iterations"] for r in answers))
    baseline, new = observed["bisection"], observed["newton"]
    error = max(abs(x-y)/abs(x) for x, y in zip(baseline["stresses"], new["stresses"]))
    passed = (relative <= POLICY["column_refinement_tolerance"] and
        0 < warm["force_n_m"] < b["force_n_m"] < faster["force_n_m"] and error < 5e-11)
    return dict(passed=bool(passed), column_64=a, column_128=b, warm_100k=warm,
        tenfold_rate=faster, column_refinement_relative_change=relative,
        paired_column_seconds=solve_s, benchmark=dict(**observed,
            max_stress_relative_difference=error,
            saved_seconds=baseline["seconds"]-new["seconds"],
            saved_percent=100*(baseline["seconds"]-new["seconds"])/baseline["seconds"],
            scope="one ten-solve prepared local-law comparison, not generator speedup"))


def bindings():
    # The executed kernel is bound where it was actually imported from; a copy outside this checkout refuses.
    names = ["tools/check_i01_column.py", "tests/test_i01_column.py",
             "cases/i01_column_v1.json", "docs/I01_COLUMN.md",
             Path(_integration_column.__file__).resolve().relative_to(ROOT).as_posix()]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        start = time.perf_counter()
        report = dict(schema="atlas.i01-column.v1", status="INCOMPLETE", scientific_acceptance=False,
            runtime=dict(python=platform.python_version(), numpy=np.__version__, system=platform.system()))
        try:
            report["source_sha256"] = bindings()
            spec = json.loads((ROOT/"cases/i01_column_v1.json").read_text(encoding="utf-8"))
            if spec["policy"] != POLICY:
                raise ValueError("case policy differs from executable")
            report.update(campaign(spec))
            report["source_unchanged"] = report["source_sha256"] == bindings()
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
