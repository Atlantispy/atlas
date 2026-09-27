"""Exact reduced nonlinear motion-admission control; not a rupture generator.

SPDX-License-Identifier: AGPL-3.0-only
No native imports, source rewrites, installations or implicit campaigns.
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
POLICY = {"max_stress_exponent": 8, "oracle_bracket_bits": 44,
          "benchmark_repetitions": 100, "oracle_relative_tolerance": 1e-12}


def rational(value, name, *, positive=False):
    if type(value) not in (int, float, Fraction):
        raise ValueError(f"{name}: finite real number required")
    if type(value) is float and not math.isfinite(value):
        raise ValueError(f"{name}: finite real number required")
    result = Fraction(value)
    if result < 0 or (positive and result == 0):
        raise ValueError(f"{name}: {'positive' if positive else 'nonnegative'} value required")
    if max(abs(result.numerator).bit_length(), result.denominator.bit_length()) > 4096:
        raise ValueError(f"{name}: input precision budget exceeded")
    return result


@dataclass(frozen=True)
class Balance:
    """F=Dv+Y+a*v**(1/n) for sliding; v=0 if F<=Y.

    F,Y: N/m; D: Pa s; a: (N/m)/(m/s)**(1/n). Constants are
    supplied integrated resistance coefficients, NOT material calibration.
    """
    force: object
    drag: object
    yield_force: object
    coefficient: object
    exponent: int

    def __post_init__(self):
        for name in ("force", "drag", "yield_force", "coefficient"):
            object.__setattr__(self, name, rational(getattr(self, name), name,
                               positive=name in ("force", "drag")))
        if type(self.exponent) is not int or not 1 <= self.exponent <= POLICY["max_stress_exponent"]:
            raise ValueError("supported integer stress exponent is 1 through 8")


class PreparedBalance:
    """Reuse an exact dimensionless polynomial, without evaluating any root."""
    def __init__(self, law):
        if not isinstance(law, Balance):
            raise ValueError("a validated Balance is required")
        self.law = law
        self.v0 = law.force / law.drag
        self.y = law.yield_force / law.force
        self.k = law.coefficient**law.exponent * self.v0 / law.force**law.exponent

    def at_least(self, speed_ratio):
        x = rational(speed_ratio, "speed ratio")
        if x > 1:
            raise ValueError("speed ratio must be at most one")
        if x == 0:
            return True
        remaining = 1-x-self.y
        return remaining >= 0 and self.k*x <= remaining**self.law.exponent

    def admits(self, relative_tolerance):
        eps = rational(relative_tolerance, "relative tolerance")
        if eps >= 1:
            raise ValueError("relative tolerance must be less than one")
        return self.at_least(1-eps)

    def bracket(self, bits=44):
        """Diagnostic/reference exact rational bisection, not the fast gate."""
        if type(bits) is not int or not 1 <= bits <= 128:
            raise ValueError("bounded bisection bits required")
        if self.y >= 1:
            return Fraction(0), Fraction(0)
        if self.y == 0 and self.k == 0:
            return Fraction(1), Fraction(1)
        lo, hi = Fraction(0), Fraction(1)
        for _ in range(bits):
            middle = (lo+hi)/2
            if self.at_least(middle):
                lo = middle
            else:
                hi = middle
        return lo, hi


def upper_float(value):
    """Outward-rounded display bound; all admission arithmetic stays exact."""
    try:
        out = float(value)
    except OverflowError as exc:
        raise ValueError("bound is not representable") from exc
    if not math.isfinite(out):
        raise ValueError("bound is not representable")
    if Fraction(out) < value:
        out = math.nextafter(out, math.inf)
    if not math.isfinite(out):
        raise ValueError("bound is not representable")
    return out


def window_admission(current, maximum, *, duration_s, relative_tolerance,
                     displacement_limit_m):
    """Conditional on a whole-window coefficient envelope, not endpoint samples.

    A caller must establish that the maximum covers the fully coupled trajectory.
    This function never promotes numerical admission to physical separation.
    """
    prepared = PreparedBalance(current)
    duration = rational(duration_s, "duration", positive=True)
    distance_limit = rational(displacement_limit_m, "displacement limit")
    eps = rational(relative_tolerance, "relative tolerance")
    if eps >= 1:
        raise ValueError("relative tolerance must be less than one")
    allowed = min(eps, distance_limit/(duration*prepared.v0))
    snapshot_ok = prepared.admits(allowed)
    result = {"snapshot_passed": snapshot_ok, "numerical_admissible": False,
              "generated_separation_authorised": False,
              "status": "REFUSED_MISSING_WINDOW_ENVELOPE"}
    if maximum is None:
        return result
    bound = PreparedBalance(maximum)
    if (maximum.force, maximum.drag, maximum.exponent) != (current.force, current.drag, current.exponent):
        raise ValueError("window requires the same fixed force, drag and exponent")
    if maximum.yield_force < current.yield_force or maximum.coefficient < current.coefficient:
        raise ValueError("window envelope excludes the current state")
    passed = bound.admits(allowed)
    result.update(numerical_admissible=passed,
                  status="PASS_CONDITIONAL_WINDOW" if passed else "REFUSED_MOTION_ERROR",
                  reference_speed_m_s=upper_float(prepared.v0),
                  relative_error_limit=upper_float(allowed),
                  duration_s=upper_float(duration))
    if passed:
        delta_v = allowed*prepared.v0
        result.update(speed_error_bound_m_s=upper_float(delta_v),
                      displacement_error_bound_m=upper_float(duration*delta_v),
                      driving_work_error_bound_J_m=upper_float(current.force*duration*delta_v))
    return result


def source_binding():
    names = ["tools/check_i01_decoupling.py", "tests/test_i01_decoupling.py",
             "cases/i01_decoupling_v1.json", "docs/I01_DECOUPLING.md"]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def controls(spec):
    rows = []
    for item in spec["controls"]:
        p = PreparedBalance(Balance(**item["law"]))
        lo, hi = p.bracket(POLICY["oracle_bracket_bits"])
        expected = item.get("exact_ratio")
        oracle_ok = expected is None or lo <= Fraction(expected) <= hi
        if item["name"] == "square_root":
            oracle_ok = abs(float((lo+hi)/2) - (3-math.sqrt(5))/2) <= POLICY["oracle_relative_tolerance"]
        passed = p.admits(item["tolerance"])
        rows.append({"name": item["name"], "admitted": passed,
                     "speed_ratio_bracket": [float(lo), float(hi)],
                     "passed": oracle_ok and passed == item["expected_admission"]})
    current = Balance(1, 1, 0, 0, 2)
    pulse = Balance(1, 1, 1, 0, 2)
    weak = Balance(1, 1, 0.001, 0.002, 2)
    kwargs = dict(duration_s=10, relative_tolerance=0.01, displacement_limit_m=0.1)
    missing = window_admission(current, None, **kwargs)
    rejected = window_admission(current, pulse, **kwargs)
    admitted = window_admission(current, weak, **kwargs)
    tight = window_admission(current, weak, duration_s=10, relative_tolerance=0.01,
                             displacement_limit_m=0.001)
    # One small matched comparison. Prepared coefficients are reused in both.
    p = PreparedBalance(Balance(1, 1, 0.001, 0.002, 3))
    eps = Fraction(1, 100)
    start = time.perf_counter()
    slow = [1-p.bracket(POLICY["oracle_bracket_bits"])[0] <= eps
            for _ in range(POLICY["benchmark_repetitions"])]
    slow_s = time.perf_counter()-start
    start = time.perf_counter()
    fast = [p.admits(eps) for _ in range(POLICY["benchmark_repetitions"])]
    fast_s = time.perf_counter()-start
    return dict(passed=all(r["passed"] for r in rows) and not missing["numerical_admissible"]
                and not rejected["numerical_admissible"] and admitted["numerical_admissible"]
                and not tight["numerical_admissible"] and slow == fast,
                cases=rows, window=dict(missing=missing, pulse=rejected, weak=admitted, tight=tight),
                benchmark=dict(count=len(fast), bisection_seconds=slow_s,
                               direct_seconds=fast_s, saved_seconds=slow_s-fast_s,
                               saved_percent=100*(slow_s-fast_s)/slow_s, decisions_equal=slow == fast,
                               scope="one small prepared-state comparison, not whole-generator speedup"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        start = time.perf_counter()
        result = dict(schema="atlas.i01-decoupling-control.v1", status="INCOMPLETE",
                      scientific_acceptance=False, runtime={"python": platform.python_version(),
                      "system": platform.system(), "machine": platform.machine()})
        try:
            result["source_sha256"] = source_binding()
            spec = json.loads((ROOT/"cases/i01_decoupling_v1.json").read_text(encoding="utf-8"))
            if spec["policy"] != POLICY:
                raise ValueError("case policy differs from executable")
            result.update(controls(spec))
            result["source_unchanged"] = result["source_sha256"] == source_binding()
            result["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if result["passed"] and result["source_unchanged"] else "FAIL"
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__,
                          error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({k: result[k] for k in ("status", "elapsed_seconds")}))
    return 0 if result["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
