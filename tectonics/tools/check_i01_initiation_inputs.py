"""MC-02 input coverage and force-curve comparison; no physics or simulation.

SPDX-License-Identifier: AGPL-3.0-only
Records remain inert data. Complete coverage is not solver/scientific admission.
The signed curve is resistance per unit strike versus cumulative convergence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "cases/i01_initiation_decision_v1.json"
MAX_BYTES = 2 * 1024 * 1024
MAX_POINTS = 8192
PUBLISHED = (
    "interface_geometry", "material_assignment", "mechanical_boundaries",
    "thermal_profiles", "creep_laws", "elastic_constants", "strength_history",
    "pressure_convention", "plastic_strain_conversion",
)
ATLAS = (
    "physical_regularisation", "release_window_and_flux", "release_work_ports",
    "refinement_policy",
)
TRACKS = ("PUBLISHED_REPRODUCTION", "ATLAS_REGULARISED")
SIGN = "positive_resists_convergence"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, expected, name):
    require(type(value) is dict and set(value) == set(expected),
            f"{name}: exact fields required: {', '.join(expected)}")


def text(value, name):
    require(type(value) is str and bool(value.strip()), f"{name}: text required")


def number(value, name, *, minimum=None, positive=False):
    require(type(value) in (int, float), f"{name}: numeric value required, not bool")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise ValueError(f"{name}: finite representable number required") from None
    require(math.isfinite(result), f"{name}: finite number required")
    require(minimum is None or result >= minimum, f"{name}: below minimum")
    require(not positive or result > 0, f"{name}: must be positive")
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    with Path(path).open("rb") as source:
        data = source.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "input exceeds bounded 2 MiB record limit")
    def invalid(value):
        raise ValueError(f"non-finite JSON number: {value}")
    return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                      parse_constant=invalid)


def bindings():
    # No native imports or package identity changes; no old receipt is repinned.
    paths = (Path(__file__), ROOT / "docs/I01_INITIATION_DECISION.md")
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


def inspect_inputs(spec):
    require(type(spec) is dict and spec.get("schema") == "atlas.i01-initiation-decision.v1",
            "expected initiation decision v1")
    require(spec.get("scientific_acceptance") is False and
            spec.get("generated_initiation_enabled") is False,
            "this specification cannot enable generation or scientific acceptance")
    protocol = spec.get("benchmark_protocol")
    keys(protocol, ("track", "inputs", "reference_curve", "comparison_policy"), "benchmark_protocol")
    require(protocol["track"] in TRACKS, "unknown comparison track")
    keys(protocol["inputs"], PUBLISHED + ATLAS, "input coverage")
    missing = []
    for name, row in protocol["inputs"].items():
        keys(row, ("basis", "definition", "source", "locator", "reviewed"), name)
        require(row["basis"] in ("MISSING", "INFERRED", "SOURCE_EXPLICIT",
                                  "SOURCE_DERIVED", "ATLAS_CHOICE"), f"{name}: basis")
        require(type(row["reviewed"]) is bool, f"{name}: reviewed must be boolean")
        if row["basis"] == "MISSING":
            require(row["definition"] is None and not row["reviewed"],
                    f"{name}: missing input cannot carry an admitted definition")
        else:
            for field in ("definition", "source", "locator"):
                text(row[field], f"{name}.{field}")
        needed = name in PUBLISHED or protocol["track"] == "ATLAS_REGULARISED"
        admitted = row["basis"] not in ("MISSING", "INFERRED") and row["reviewed"]
        if protocol["track"] == "PUBLISHED_REPRODUCTION" and name in PUBLISHED:
            admitted = admitted and row["basis"] != "ATLAS_CHOICE"
        if needed and not admitted:
            missing.append(name)
    if protocol["reference_curve"] is None:
        missing.append("reference_curve")
    else:
        curve(protocol["reference_curve"], reference=True)
    if protocol["comparison_policy"] is None:
        missing.append("comparison_policy")
    else:
        policy(protocol["comparison_policy"])
    return dict(status="INCOMPLETE" if missing else "COMPLETE_FOR_REVIEW",
                missing=missing, track=protocol["track"], scientific_acceptance=False,
                runnable_configuration=False)


def curve(row, *, reference=False):
    expected = ["convergence_m", "force_N_per_m", "sign_convention"]
    if reference:
        expected += ["uncertainty_N_per_m", "source", "locator", "uncertainty_basis"]
    keys(row, expected, "reference curve" if reference else "candidate curve")
    require(row["sign_convention"] == SIGN, "force sign convention mismatch")
    xs, ys = row["convergence_m"], row["force_N_per_m"]
    require(type(xs) is list and type(ys) is list and
            2 <= len(xs) <= MAX_POINTS and len(xs) == len(ys), "bounded matching curve arrays required")
    xs = tuple(number(x, "convergence_m", minimum=0) for x in xs)
    ys = tuple(number(y, "force_N_per_m") for y in ys)
    require(all(b > a for a, b in zip(xs, xs[1:])), "convergence must be strictly increasing")
    uncertainty = (0.0,) * len(xs)
    if reference:
        for name in ("source", "locator", "uncertainty_basis"):
            text(row[name], name)
        us = row["uncertainty_N_per_m"]
        require(type(us) is list and len(us) == len(xs), "matching reference uncertainty required")
        uncertainty = tuple(number(u, "uncertainty", minimum=0) for u in us)
    return xs, ys, uncertainty


def policy(row):
    keys(row, ("interval_m", "max_gap_m", "force_allowance_N_per_m",
               "work_allowance_J_per_m", "basis", "reviewed"), "comparison policy")
    require(row["reviewed"] is True, "comparison allowances need explicit review")
    text(row["basis"], "comparison allowance basis")
    require(type(row["interval_m"]) is list and len(row["interval_m"]) == 2,
            "fixed convergence interval required")
    start, end = (number(x, "interval", minimum=0) for x in row["interval_m"])
    require(end > start, "comparison interval must have positive length")
    gap = number(row["max_gap_m"], "max_gap_m", positive=True)
    force = number(row["force_allowance_N_per_m"], "force allowance", minimum=0)
    work = number(row["work_allowance_J_per_m"], "work allowance", minimum=0)
    return start, end, gap, force, work


def prepare(spec):
    coverage = inspect_inputs(spec)
    require(coverage["status"] == "COMPLETE_FOR_REVIEW",
            "incomplete benchmark inputs: " + ", ".join(coverage["missing"]))
    protocol = spec["benchmark_protocol"]
    start, end, gap, _, _ = policy(protocol["comparison_policy"])
    ref = curve(protocol["reference_curve"], reference=True)
    window(ref, start, end, gap)
    payload = dict(schema="atlas.i01-initiation-comparison-plan.v1", source_sha256=bindings(),
                   specification=spec, scientific_acceptance=False, runnable_configuration=False)
    # JSON round-trip detaches the prepared record from caller-owned dictionaries.
    return json.loads(canonical(dict(plan_sha256=digest(payload), payload=payload)))


def window(values, start, end, gap):
    xs, _, _ = values
    require(xs[0] <= start and xs[-1] >= end, "curve does not cover fixed interval; no extrapolation")
    require(all(b-a <= gap for a, b in zip(xs, xs[1:]) if b > start and a < end),
            "sampling gap exceeds the predeclared maximum")


def sample(values, points):
    """One monotone scan; do not resample just at the reference knots."""
    xs, ys, us = values
    i = 0
    for x in points:
        while i < len(xs)-2 and xs[i+1] < x:
            i += 1
        t = (x-xs[i])/(xs[i+1]-xs[i])
        yield ((1-t)*ys[i]+t*ys[i+1], (1-t)*us[i]+t*us[i+1])


def compare(plan, candidate):
    keys(plan, ("plan_sha256", "payload"), "plan")
    payload = plan["payload"]
    keys(payload, ("schema", "source_sha256", "specification", "scientific_acceptance",
                   "runnable_configuration"), "plan payload")
    require(payload["schema"] == "atlas.i01-initiation-comparison-plan.v1" and
            payload["scientific_acceptance"] is False and payload["runnable_configuration"] is False,
            "wrong plan scope")
    require(plan["plan_sha256"] == digest(payload), "comparison plan changed")
    require(payload["source_sha256"] == bindings(), "comparison implementation/method changed")
    keys(candidate, ("plan_sha256", "run_identity", "curve"), "candidate")
    require(candidate["plan_sha256"] == plan["plan_sha256"], "candidate belongs to a different plan")
    text(candidate["run_identity"], "candidate run identity")
    spec = payload["specification"]
    require(inspect_inputs(spec)["status"] == "COMPLETE_FOR_REVIEW", "plan inputs incomplete")
    protocol = spec["benchmark_protocol"]
    start, end, gap, force_allowance, work_allowance = policy(protocol["comparison_policy"])
    ref = curve(protocol["reference_curve"], reference=True)
    actual = curve(candidate["curve"])
    window(ref, start, end, gap)
    window(actual, start, end, gap)
    # Union captures candidate peaks between reference knots. The bounded sort is
    # performed once; all interpolation/integration work below is linear.
    points = sorted({start, end} | {x for x in ref[0]+actual[0] if start < x < end})
    rr, aa = list(sample(ref, points)), list(sample(actual, points))
    errors = [a[0]-r[0] for a, r in zip(aa, rr)]
    excess = max(max(abs(d)-r[1], 0.0) for d, r in zip(errors, rr))
    def integral(values):
        return math.fsum((b-a)*(values[i]/2+values[i+1]/2)
                         for i, (a, b) in enumerate(zip(points, points[1:])))
    ref_work = integral([r[0] for r in rr])
    actual_work = integral([a[0] for a in aa])
    uncertainty_work = integral([r[1] for r in rr])
    work_error = abs(integral(errors))
    # Signed work cancellation cannot hide an excursion: the force gate is separate.
    metrics = dict(max_abs_force_error_N_per_m=max(map(abs, errors)),
                   max_force_error_beyond_uncertainty_N_per_m=excess,
                   reference_signed_work_J_per_m=ref_work, candidate_signed_work_J_per_m=actual_work,
                   signed_work_error_J_per_m=work_error, work_uncertainty_J_per_m=uncertainty_work)
    for name, value in metrics.items():
        number(value, name)  # fail closed on overflow; never report a NaN pass
    work_budget = number(uncertainty_work + work_allowance, "combined work allowance")
    passed = excess <= force_allowance and work_error <= work_budget
    require(payload["source_sha256"] == bindings(), "comparison sources changed during evaluation")
    return dict(schema="atlas.i01-initiation-curve-comparison.v1",
                status="PASS_DECLARED_CURVE_ONLY" if passed else "FAIL",
                track=protocol["track"], plan_sha256=plan["plan_sha256"],
                candidate_sha256=digest(candidate), run_identity=candidate["run_identity"],
                interval_m=[start, end], evaluated_knots=len(points), **metrics,
                scientific_acceptance=False, release_classification="NOT_ASSESSED")


def write_new(path, value):
    encoded = json.dumps(value, indent=2, allow_nan=False) + "\n"
    require(len(encoded.encode("utf-8")) <= MAX_BYTES, "output exceeds bounded 2 MiB record limit")
    with Path(path).open("x", encoding="utf-8", newline="\n") as output:
        output.write(encoded)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "prepare"):
        command = commands.add_parser(name)
        command.add_argument("--spec", type=Path, default=DEFAULT)
        if name == "prepare":
            command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("compare")
    command.add_argument("--plan", type=Path, required=True)
    command.add_argument("--candidate", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_inputs(read_json(args.spec))
            print(json.dumps(result, allow_nan=False))
            return 2 if result["missing"] else 0
        if args.command == "prepare":
            result = prepare(read_json(args.spec))
            write_new(args.output, result)
            print(json.dumps(dict(status="PREPARED_CURVE_COMPARISON_ONLY", plan_sha256=result["plan_sha256"])))
            return 0
        result = compare(read_json(args.plan), read_json(args.candidate))
        write_new(args.output, result)
        print(json.dumps(result, allow_nan=False))
        return 0 if result["status"] == "PASS_DECLARED_CURVE_ONLY" else 1
    except (ValueError, OSError, TypeError, OverflowError) as exc:
        # Paths may be private. Public stdout contains no exception filename.
        message = type(exc).__name__ if isinstance(exc, OSError) else str(exc)
        print(json.dumps(dict(status="REFUSED", error=message)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
