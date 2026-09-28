"""Bounded force/drag/column coupling; WORKING NON-CANON.

I02.2a: Drive and the motion root are owned by atlas_tectonics._integration_motion.
This tool re-exports those same objects and keeps its fixed-temperature evolution,
case, campaign and CLI.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from threadpoolctl import threadpool_limits

from atlas_tectonics import _integration_column, _integration_motion, _integration_weakening
# The package-owned motion root, re-exported: these are the same objects, not copies.
from atlas_tectonics._integration_motion import FORCE_TOL, MAX_ITERATIONS, Drive, solve

import check_i01_weakening as w

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/i01_motion_coupling_v1.json"
RECEIPT = ROOT / "evidence/i01-weakening-r2.json"
# Retained helper sources, their package owners included, whose bytes the reviewed receipt must have recorded.
REVIEWED_HELPERS = ("tools/check_i01_weakening.py", "tools/check_i01_column.py", "cases/i01_weakening_v1.json",
                    "src/atlas_tectonics/_integration_weakening.py", "src/atlas_tectonics/_integration_column.py")


def evolve(prep, law, kappa0, drive, *, duration_s, steps, strain_bound=.05,
           warm_start=True, method="newton", deadline=None):
    """Heun history integration; fixed column, external drive and disjoint drag.

    Retain only current state, one predictor and integrated scalar accounts.
    Compute accepted endpoint before booking; an over-strain trial books nothing.
    """
    if type(steps) is not int or not 1 <= steps <= 256:
        raise ValueError("integer step count 1..256 required")
    if type(warm_start) is not bool:
        raise ValueError("warm_start must be boolean")
    duration = w.positive(duration_s, "duration")
    bound = w.strain_limit(strain_bound)
    initial = w.history_array(prep, kappa0).copy()
    kappa, strain = initial.copy(), 0.
    dt = duration / steps
    current = solve(prep, law, kappa, drive, method=method, deadline=deadline)
    first_velocity = current["velocity_m_s"]
    keys = ("drive", "drag", "creep", "plastic")
    energy = dict.fromkeys(keys, 0.)
    evaluations, iterations = current["evaluations"], current["iterations"]
    max_residual, max_power = current["force_relative"], current["power_relative"]
    accepted, status = 0, "COMPLETE"
    for _ in range(steps):
        w.check_deadline(deadline)
        predictor = solve(prep, law, kappa + dt * current["kdot"], drive, method=method,
                          warm=current if warm_start else None, deadline=deadline)
        evaluations += predictor["evaluations"]
        iterations += predictor["iterations"]
        next_strain = strain + dt * (current["rate"] + predictor["rate"]) / 2
        if abs(next_strain) > bound:
            status = "REFUSED_SMALL_STRAIN"
            break
        next_kappa = kappa + dt * (current["kdot"] + predictor["kdot"]) / 2
        if (not np.all(np.isfinite(next_kappa)) or np.any(next_kappa < kappa)
                or np.any(next_kappa - initial > 2 * abs(next_strain) * (1 + 1e-10))):
            raise ValueError("plastic history violated small-strain account")
        endpoint = solve(prep, law, next_kappa, drive, method=method,
                         warm=predictor if warm_start else None, deadline=deadline)
        evaluations += endpoint["evaluations"]
        iterations += endpoint["iterations"]
        for key in keys:
            energy[key] += dt * (current[key + "_power_w_m"] + predictor[key + "_power_w_m"]) / 2
        for state in (predictor, endpoint):
            max_residual = max(max_residual, state["force_relative"])
            max_power = max(max_power, state["power_relative"])
        kappa, strain, current = next_kappa, next_strain, endpoint
        accepted += 1
    partition = abs(energy["drive"] - sum(energy[k] for k in keys[1:])) / max(energy["drive"], w.TINY)
    return dict(status=status, accepted_steps=accepted, elapsed_s=accepted * dt,
                strain=strain, displacement_m=strain * drive.width_m, kappa=kappa,
                velocity_start_m_s=first_velocity, velocity_end_m_s=current["velocity_m_s"],
                energy_j_m=energy, work_relative=partition, max_force_relative=max_residual,
                max_power_relative=max_power, evaluations=evaluations, iterations=iterations,
                final=current)


def load_case():
    spec = json.loads(CASE.read_text(encoding="utf-8"))
    if spec["schema"] != "atlas.i01-motion-coupling-case.v1":
        raise ValueError("unsupported motion case")
    Drive(spec["drive_n_m"], spec["drag_pa_s"], spec["width_m"])
    w.strain_limit(spec["strain_bound"])
    for key in ("duration_s", "time_relative", "depth_relative", "parity_relative", "maximum_seconds"):
        w.positive(spec[key], key)
    for key, ceiling in (("orders", 128), ("steps", 256)):
        if (len(spec[key]) != 3 or any(type(n) is not int or not 1 <= n <= ceiling for n in spec[key])
                or spec[key][1] != 2 * spec[key][0] or spec[key][2] != 2 * spec[key][1]):
            raise ValueError("three doubled bounded refinements required")
    return spec


def compact(out):
    return {k: v for k, v in out.items() if k not in ("final", "kappa")}


def campaign(spec, deadline):
    prior = w.load_case()
    law = w.law_of(prior)
    drive = Drive(spec["drive_n_m"], spec["drag_pa_s"], spec["width_m"])
    def run(order, steps, law=law, **kw):
        prep, _ = w.base_prepare(prior, order=order)
        return evolve(prep, law, w.initial_history(prep, prior), drive,
                      duration_s=spec["duration_s"], steps=steps,
                      strain_bound=spec["strain_bound"], deadline=deadline, **kw)
    times = [run(spec["orders"][1], n) for n in spec["steps"]]
    depths = [run(n, spec["steps"][1]) for n in spec["orders"]]
    off = run(spec["orders"][1], spec["steps"][1], law=w.OFF)
    final = times[-1]
    time_change = w.relative_change(times[-1]["velocity_end_m_s"], times[-2]["velocity_end_m_s"])
    depth_change = w.relative_change(depths[-1]["velocity_end_m_s"], depths[-2]["velocity_end_m_s"])
    # Same physical history, differing only starting guesses; one matched observation.
    comparisons = []
    for warm_start in (False, True):
        begin = time.perf_counter()
        result = run(spec["orders"][1], spec["steps"][1], warm_start=warm_start)
        comparisons.append((time.perf_counter() - begin, result))
    cold_time, cold = comparisons[0]
    warm_time, warm = comparisons[1]
    parity = max(w.relative_change(warm["strain"], cold["strain"]),
                 w.relative_change(warm["velocity_end_m_s"], cold["velocity_end_m_s"]),
                 float(np.max(np.abs(warm["kappa"] - cold["kappa"]))))
    # Independent scalar solver and both signs at the same supplied state.
    prep, _ = w.base_prepare(prior, order=spec["orders"][1])
    kappa = w.initial_history(prep, prior)
    roots = []
    for sign in (1, -1):
        forcing = Drive(sign * drive.force_n_m, drive.drag_pa_s, drive.width_m)
        a = solve(prep, law, kappa, forcing, deadline=deadline)
        b = solve(prep, law, kappa, forcing, method="brent", deadline=deadline)
        roots.append(dict(sign=sign, velocity_m_s=a["velocity_m_s"],
                          relative=w.relative_change(a["rate"], b["rate"]),
                          force_relative=a["force_relative"], power_relative=a["power_relative"]))
    checks = dict(complete=all(r["status"] == "COMPLETE" for r in times + depths + [off, cold, warm]),
                  time=time_change <= spec["time_relative"], depth=depth_change <= spec["depth_relative"],
                  evolving=final["velocity_end_m_s"] > final["velocity_start_m_s"],
                  fixed_strength=off["velocity_end_m_s"] == off["velocity_start_m_s"],
                  work=max(r["work_relative"] for r in times + depths) <= 2e-10,
                  reuse_parity=parity <= spec["parity_relative"],
                  root_parity=max(r["relative"] for r in roots) <= spec["parity_relative"])
    return w.verdict(checks, time_refinement=[compact(r) for r in times],
                     depth_refinement=[compact(r) for r in depths],
                     fixed_strength=compact(off), time_relative=time_change, depth_relative=depth_change,
                     root_comparison=roots, warm_start=dict(cold_seconds=cold_time, warm_seconds=warm_time,
                     saved_seconds=cold_time-warm_time, saved_percent=100*(1-warm_time/cold_time),
                     parity=parity, cold_evaluations=cold["evaluations"], warm_evaluations=warm["evaluations"],
                     cold_iterations=cold["iterations"], warm_iterations=warm["iterations"]))


def bindings():
    # I02.2a: the executed package owners are bound where they were imported from, outside ROOT refusing.
    paths = [Path(__file__), CASE, ROOT / "docs/I01_MOTION_COUPLING.md",
             ROOT / "tests/test_i01_motion_coupling.py", Path(w.__file__), Path(w.column.__file__),
             w.CASE, RECEIPT, Path(_integration_motion.__file__), Path(_integration_weakening.__file__),
             Path(_integration_column.__file__)]
    return {p.resolve().relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        start = time.perf_counter()
        result = dict(schema="atlas.i01-motion-coupling-evidence.v1", status="INCOMPLETE",
                      scientific_acceptance=False, runtime=dict(python=platform.python_version(),
                      numpy=np.__version__, scipy=scipy.__version__, system=platform.system(), blas_threads=1))
        try:
            before, spec = bindings(), load_case()
            reviewed = json.loads(RECEIPT.read_text(encoding="utf-8"))["source_sha256"]
            match = {p: reviewed.get(p) == before[p] for p in REVIEWED_HELPERS}
            if not all(match.values()):
                raise ValueError("retained helper differs from reviewed evidence")
            result.update(source_sha256=before, reviewed_helper_match=match, case=spec,
                          controls=campaign(spec, start + spec["maximum_seconds"]))
            result["source_unchanged"] = before == bindings()
            result["status"] = ("PASS_BOUNDED_MOTION_COUPLING_ONLY" if result["source_unchanged"]
                                and result["controls"]["passed"] else "FAIL")
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__)
        result["elapsed_seconds"] = time.perf_counter() - start
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result.get(k) for k in ("status", "elapsed_seconds", "error_type")}))
    return 0 if result["status"] == "PASS_BOUNDED_MOTION_COUPLING_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
