"""Exact contacts of declared affine planar junction paths, not reorganisation.

SPDX-License-Identifier: AGPL-3.0-only
No native imports, graph writes, physical thresholds or historical repinning.
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
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
MODEL = "affine_planar_junction_paths_v1"
POLICY = {"input_integer_bits": 1024, "arithmetic_bits": 16384,
          "benchmark_calls": 1000, "benchmark_repeats": 5, "maximum_seconds": 10.0}


def number(value):
    if type(value) not in (int, float, Fraction):
        raise ValueError("finite built-in real or bounded exact fraction required")
    if type(value) is int:
        if value.bit_length() > POLICY["input_integer_bits"]:
            raise ValueError("integer input exceeds resource bound")
    elif type(value) is float and not math.isfinite(value):
        raise ValueError("finite real required")
    return bounded(Fraction(value))


def bounded(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > POLICY["arithmetic_bits"]:
        raise ValueError("exact arithmetic exceeds resource bound")
    return value


def vector(value):
    if type(value) not in (list, tuple) or len(value) != 2:
        raise ValueError("two planar coordinates required")
    return tuple(number(v) for v in value)


def label(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.isprintable() or not value.strip():
        raise ValueError("bounded nonempty identity required")
    return value


def ratio(value):
    return None if value is None else {"numerator": str(value.numerator), "denominator": str(value.denominator)}


@dataclass(frozen=True)
class Contact:
    status: str
    parent_id: str
    edge_id: str
    offset_s: Fraction | None

    def record(self):
        return {"status": self.status, "parent_id": self.parent_id, "edge_id": self.edge_id,
                "offset_s_exact": ratio(self.offset_s), "trajectory_model": MODEL,
                "topology_change_authorised": False}


@dataclass(frozen=True, init=False)
class PreparedContact:
    """Copied immutable path coefficients. Coordinates m; velocities m/s.

    Offsets are measured from one caller-owned parent epoch, not accumulated
    floats. This object authenticates no external solver state or physical law.
    """
    parent_id: str
    edge_id: str
    validity_s: Fraction
    displacement: tuple[Fraction, Fraction]
    relative_velocity: tuple[Fraction, Fraction]
    root_s: Fraction | None
    coincident: bool

    def __init__(self, x_left, x_right, v_left, v_right, *, validity_s, parent_id, edge_id, model):
        if model != MODEL:
            raise ValueError("only declared affine planar paths supported")
        p, q, v, w = (vector(x) for x in (x_left, x_right, v_left, v_right))
        horizon = number(validity_s)
        if horizon <= 0:
            raise ValueError("positive path validity horizon required")
        d = tuple(bounded(b-a) for a, b in zip(p, q))
        dv = tuple(bounded(b-a) for a, b in zip(v, w))
        root = None
        coincident = not any(d) and not any(dv)
        if any(dv):
            i = next(i for i in range(2) if dv[i])
            candidate = bounded(-d[i]/dv[i])
            if all(bounded(d[j]+bounded(candidate*dv[j])) == 0 for j in range(2)):
                root = candidate
        for name, value in {"parent_id": label(parent_id), "edge_id": label(edge_id),
                            "validity_s": horizon, "displacement": d,
                            "relative_velocity": dv, "root_s": root,
                            "coincident": coincident}.items():
            object.__setattr__(self, name, value)

    def query(self, start_s, end_s):
        start, end = number(start_s), number(end_s)
        if not 0 <= start < end <= self.validity_s:
            raise ValueError("query must be a positive interval inside parent validity")
        if self.coincident:
            return Contact("COINCIDENT_INTERVAL_NOT_ISOLATED_EVENT", self.parent_id, self.edge_id, None)
        root = self.root_s
        if root is None or not start <= root <= end:
            return Contact("NO_CONTACT_ON_DECLARED_PATH", self.parent_id, self.edge_id, None)
        status = "CONTACT_AT_WINDOW_START" if root == start else "COLLISION_CANDIDATE_NOT_REORGANISED"
        return Contact(status, self.parent_id, self.edge_id, root)


def fixture(**changes):
    kw = {"x_left": (0, 0), "x_right": (12, 0), "v_left": (1, 0), "v_right": (-2, 0),
          "validity_s": 8, "parent_id": "manufactured-parent", "edge_id": "shared-edge",
          "model": MODEL}
    kw.update(changes)
    return kw


def bindings():
    names = ("tools/check_i01_junction_events.py", "tests/test_i01_junction_events.py",
             "cases/i01_junction_events_v1.json", "docs/I01_JUNCTION_EVENTS.md")
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def controls(spec):
    expected = {"schema": "atlas.i01-junction-events-case.v1", "model": MODEL, "policy": POLICY,
                "fixture": {"gap_m": 12, "closing_speed_m_s": 3, "root_s": 4, "validity_s": 8}}
    if spec != expected:
        raise ValueError("case differs from predeclared controls")
    start = time.perf_counter()
    p = PreparedContact(**fixture())
    event = p.query(0, 8)
    # Independent scalar gap polynomial: (12-3*t)^2 has a double root at 4.
    checks = {"exact_double_root": event.offset_s == 4 and (12-3*4)**2 == 0,
              "no_sign_change_needed": (12-3*0)**2 > 0 and (12-3*8)**2 > 0,
              "no_past_replay_claim": p.query(5, 8).offset_s is None,
              "endpoint_contact_distinct": p.query(4, 8).status == "CONTACT_AT_WINDOW_START",
              "near_miss_preserved": PreparedContact(**fixture(x_right=(12, 5e-324))).query(0, 8).offset_s is None,
              "persistent_contact_distinct": PreparedContact(**fixture(x_right=(0, 0), v_right=(1, 0))).query(0, 8).status == "COINCIDENT_INTERVAL_NOT_ISOLATED_EVENT",
              "moving_frame_invariant": PreparedContact(**fixture(x_left=(100, 200), x_right=(112, 200), v_left=(21, -7), v_right=(18, -7))).query(0, 8) == event,
              "no_topology_permission": event.record()["topology_change_authorised"] is False}
    samples = {"prepared": [], "rebuilt": []}
    out = {}
    for rep in range(POLICY["benchmark_repeats"]):
        modes = ("prepared", "rebuilt") if rep % 2 == 0 else ("rebuilt", "prepared")
        for mode in modes:
            begin = time.perf_counter()
            for _ in range(POLICY["benchmark_calls"]):
                op = p if mode == "prepared" else PreparedContact(**fixture())
                out[mode] = op.query(0, 8)
            samples[mode].append(time.perf_counter()-begin)
            if time.perf_counter()-start > POLICY["maximum_seconds"]:
                raise ValueError("bounded campaign deadline exceeded")
    checks["exact_reuse_parity"] = out["prepared"] == out["rebuilt"]
    med = {k: statistics.median(v) for k, v in samples.items()}
    return {"passed": all(checks.values()), "checks": checks, "event": event.record(),
            "benchmark": {"seconds": samples, "medians_s": med,
                          "saved_s": med["rebuilt"]-med["prepared"],
                          "saved_percent": 100*(1-med["prepared"]/med["rebuilt"]),
                          "scope": "1000 queries on identical supplied paths; preparation reuse only, not solver/world speedup"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        start = time.perf_counter()
        result = {"schema": "atlas.i01-junction-events-control.v1", "status": "INCOMPLETE",
                  "scientific_acceptance": False, "generated_reorganisation": False,
                  "runtime": {"python": platform.python_version(), "system": platform.system()}}
        try:
            result["source_sha256"] = bindings()
            spec = json.loads((ROOT/"cases/i01_junction_events_v1.json").read_text(encoding="utf-8"))
            result.update(controls(spec))
            result["source_unchanged"] = result["source_sha256"] == bindings()
            result["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if (result["passed"] and result["source_unchanged"]
                and time.perf_counter()-start <= POLICY["maximum_seconds"]) else "FAIL"
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__)
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("status", "elapsed_seconds")}))
    return 0 if result["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
