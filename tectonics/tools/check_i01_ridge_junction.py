"""Exact local feasibility of a proposed all-ridge junction continuation.

SPDX-License-Identifier: AGPL-3.0-only
Not a birth law, complete geometry certificate, or graph mutation.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

from check_i01_junction_events import bounded, label, number, ratio, vector

ROOT = Path(__file__).resolve().parents[1]
MODEL = "symmetric_ridge_outgoing_candidate_v1"
POLICY = {"calls": 300, "repeats": 5, "maximum_seconds": 10.0}


def sub(a, b):
    return tuple(bounded(x-y) for x, y in zip(a, b))


def dot(a, b):
    return bounded(sum((bounded(x*y) for x, y in zip(a, b)), Fraction(0)))


def cross(a, b):
    return bounded(bounded(a[0]*b[1])-bounded(a[1]*b[0]))


def solve_pair(n, m, b, c):
    determinant = cross(n, m)
    if not determinant:
        raise ValueError("outer ridge constraints underdetermined")
    return (bounded(bounded(b*m[1]-c*n[1])/determinant),
            bounded(bounded(n[0]*c-m[0]*b)/determinant))


@dataclass(frozen=True, init=False)
class PreparedCandidate:
    """At contact, test ACD and BCD endpoints of a proposed CD ridge.

    Four plate velocities in m/s, ordered A,B,C,D. Five dimensionless normals
    oriented A->C,A->D,B->C,B->D,C->D. Normals need not be unit length.
    Right-handed planar coordinates; positive CD direction is (-n_y,n_x),
    ACD->BCD. The caller still owns cyclic order, exterior rays and birth physics.
    """
    parent_id: str
    candidate_id: str
    plate_ids: tuple[str, ...]
    validity_s: Fraction
    frame_velocity: tuple[Fraction, Fraction]
    junction_a_relative: tuple[Fraction, Fraction]
    junction_b_relative: tuple[Fraction, Fraction]
    relative_growth: tuple[Fraction, Fraction]
    growth_squared: Fraction
    normal_residuals: tuple[Fraction, Fraction]
    oriented_growth: Fraction
    status: str

    def __init__(self, velocities, normals, *, parent_id, candidate_id,
                 plate_ids, validity_s, model):
        if model != MODEL:
            raise ValueError("only declared planar symmetric all-ridge model supported")
        if type(velocities) not in (list, tuple) or len(velocities) != 4:
            raise ValueError("four ordered plate velocities required")
        if type(normals) not in (list, tuple) or len(normals) != 5:
            raise ValueError("five ordered ownership normals required")
        if type(plate_ids) not in (list, tuple) or len(plate_ids) != 4:
            raise ValueError("four plate identities required")
        ids = tuple(label(p) for p in plate_ids)
        if len(set(ids)) != 4:
            raise ValueError("four distinct plates required")
        parent, candidate = label(parent_id), label(candidate_id)
        horizon = number(validity_s)
        if horizon <= 0:
            raise ValueError("positive post-contact validity horizon required")
        v = tuple(vector(p) for p in velocities)
        ns = tuple(vector(p) for p in normals)
        if any(not any(n) for n in ns):
            raise ValueError("nonzero ownership normals required")
        # Relative frame eliminates arbitrary observer translation before solving.
        rel = tuple(sub(p, v[0]) for p in v)
        pairs = ((0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
        speeds = []
        for n, (i, j) in zip(ns, pairs):
            if dot(n, sub(rel[j], rel[i])) <= 0:
                raise ValueError("every declared ridge must have positive oriented opening")
            average = tuple(bounded((x+y)/2) for x, y in zip(rel[i], rel[j]))
            speeds.append(dot(n, average))
        ja = solve_pair(ns[0], ns[1], speeds[0], speeds[1])
        jb = solve_pair(ns[2], ns[3], speeds[2], speeds[3])
        w = sub(jb, ja)
        g2 = dot(w, w)
        residuals = tuple(bounded(dot(ns[4], j)-speeds[4]) for j in (ja, jb))
        oriented = dot((-ns[4][1], ns[4][0]), w)
        if any(residuals):
            status = "INCOMPATIBLE_NEW_RIDGE_MOTION"
        elif not g2:
            status = "NO_FIRST_ORDER_GROWTH"
        elif oriented <= 0:
            status = "REVERSED_ORIENTED_GROWTH"
        else:
            status = "LOCALLY_FEASIBLE_NOT_GENERATED"
        for key, value in {
            "parent_id": parent, "candidate_id": candidate, "plate_ids": ids,
            "validity_s": horizon, "frame_velocity": v[0],
            "junction_a_relative": ja, "junction_b_relative": jb,
            "relative_growth": w, "growth_squared": g2,
            "normal_residuals": residuals, "oriented_growth": oriented,
            "status": status,
        }.items():
            object.__setattr__(self, key, value)

    def separation_squared(self, elapsed_s):
        """Squared distance (m2), not permission to advance or commit a world."""
        elapsed = number(elapsed_s)
        if not 0 < elapsed <= self.validity_s:
            raise ValueError("positive elapsed time within the declared horizon required")
        if self.status != "LOCALLY_FEASIBLE_NOT_GENERATED":
            raise ValueError("no locally feasible forward branch")
        return bounded(bounded(elapsed*elapsed)*self.growth_squared)

    def record(self):
        return {"model": MODEL, "status": self.status,
                "parent_id": self.parent_id, "candidate_id": self.candidate_id,
                "plate_ids": self.plate_ids, "validity_s_exact": ratio(self.validity_s),
                "frame_velocity_m_s_exact": [ratio(v) for v in self.frame_velocity],
                "junction_a_relative_m_s_exact": [ratio(v) for v in self.junction_a_relative],
                "junction_b_relative_m_s_exact": [ratio(v) for v in self.junction_b_relative],
                "growth_squared_m2_s2_exact": ratio(self.growth_squared),
                "normal_constraint_residuals_exact": [ratio(v) for v in self.normal_residuals],
                "topology_change_authorised": False,
                "physical_birth_verified": False, "global_geometry_verified": False}


def fixture(**changes):
    values = {"velocities": [(-2, 0), (2, 0), (0, 1), (0, -1)],
              "normals": [(1, 1), (1, -1), (-1, 1), (-1, -1), (0, -1)],
              "plate_ids": ["A", "B", "C", "D"], "validity_s": 8,
              "parent_id": "manufactured-contact", "candidate_id": "proposed-CD",
              "model": MODEL}
    values.update(changes)
    return values


def bindings():
    files = ("tools/check_i01_ridge_junction.py", "tests/test_i01_ridge_junction.py",
             "cases/i01_ridge_junction_v1.json", "docs/I01_RIDGE_JUNCTION.md",
             "tools/check_i01_junction_events.py")
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}


def controls(spec):
    expected = {"schema": "atlas.i01-ridge-junction-case.v1", "model": MODEL,
                "policy": POLICY, "fixture": {"side_speed_m_s": 2, "top_speed_m_s": 1,
                                               "growth_squared_m2_s2": 1}}
    if spec != expected:
        raise ValueError("case differs from predeclared controls")
    p = PreparedCandidate(**fixture())
    incompatible = PreparedCandidate(**fixture(normals=[(1, 1), (1, -1), (-1, 1), (-1, -1), (1, -1)]))
    stopped = PreparedCandidate(**fixture(velocities=[(-1, 0), (1, 0), (0, 1), (0, -1)]))
    reversed_case = PreparedCandidate(**fixture(velocities=[(-1, 0), (1, 0), (0, 2), (0, -2)]))
    moving = PreparedCandidate(**fixture(velocities=[(x+19, y-7) for x, y in fixture()["velocities"]]))
    rotated = PreparedCandidate(**fixture(velocities=[(-y, x) for x, y in fixture()["velocities"]],
                                          normals=[(-y, x) for x, y in fixture()["normals"]]))
    checks = {"independent_linear_solution": p.junction_a_relative == (Fraction(3, 2), 0)
              and p.junction_b_relative == (Fraction(5, 2), 0) and p.growth_squared == 1,
              "independent_forward_length": p.separation_squared(3) == 9,
              "new_ridge_law_both_endpoints": incompatible.status == "INCOMPATIBLE_NEW_RIDGE_MOTION",
              "stationary_not_a_birth": stopped.status == "NO_FIRST_ORDER_GROWTH",
              "unsigned_length_not_sufficient": reversed_case.growth_squared == 1
              and reversed_case.status == "REVERSED_ORIENTED_GROWTH",
              "observer_invariance": moving.relative_growth == p.relative_growth
              and moving.junction_a_relative == p.junction_a_relative,
              "rotation_invariance": rotated.growth_squared == 1 and rotated.status == p.status,
              "no_physical_permission": not any(p.record()[k] for k in
                ("topology_change_authorised", "physical_birth_verified", "global_geometry_verified"))}
    samples = {"prepared": [], "rebuilt": []}
    start = time.perf_counter()
    results = {}
    for rep in range(POLICY["repeats"]):
        for mode in (("prepared", "rebuilt") if rep % 2 == 0 else ("rebuilt", "prepared")):
            begin = time.perf_counter()
            for _ in range(POLICY["calls"]):
                op = p if mode == "prepared" else PreparedCandidate(**fixture())
                results[mode] = op.separation_squared(3)
            samples[mode].append(time.perf_counter()-begin)
            if time.perf_counter()-start > POLICY["maximum_seconds"]:
                raise ValueError("bounded campaign deadline exceeded")
    checks["exact_reuse_parity"] = results["prepared"] == results["rebuilt"] == 9
    med = {k: statistics.median(v) for k, v in samples.items()}
    return {"passed": all(checks.values()), "checks": checks, "candidate": p.record(),
            "benchmark": {"seconds": samples, "medians_s": med,
                "saved_s": med["rebuilt"]-med["prepared"],
                "saved_percent": 100*(1-med["prepared"]/med["rebuilt"]),
                "scope": "300 repeated length queries; immutable preparation reuse, not world speedup"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        start = time.perf_counter()
        result = {"schema": "atlas.i01-ridge-junction-control.v1", "status": "INCOMPLETE",
                  "scientific_acceptance": False, "generated_reorganisation": False,
                  "runtime": {"python": platform.python_version(), "system": platform.system()}}
        try:
            result["source_sha256"] = bindings()
            result.update(controls(json.loads((ROOT/"cases/i01_ridge_junction_v1.json").read_text(encoding="utf-8"))))
            result["source_unchanged"] = result["source_sha256"] == bindings()
            result["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if result["passed"] and result["source_unchanged"] and time.perf_counter()-start <= POLICY["maximum_seconds"] else "FAIL"
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__)
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("status", "elapsed_seconds")}))
    return 0 if result["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
