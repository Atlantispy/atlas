"""Bounded source-bound Plan40B arithmetic controls, never a heat worker/run.

Requires the existing gmpy2 environment. Extracts only the named numerical
definitions from the selected source, disables H3 dispatch, and makes an in-memory
feasibility variant. No source pins, production files or runtime settings change.
"""
from __future__ import annotations

if not __debug__:
    raise RuntimeError('Control validation requires assertions; do not use Python -O or -OO')

import argparse
import ast
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path

import gmpy2 as G

ROOT = Path(__file__).resolve().parents[5]
MAP = ROOT / "tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json"
MAP_SHA = "ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc"
MEMBER = "source/helpers/private_heat_certification_kernel_r1.py"
NAMES = {"Arithmetic", "Unresolved", "_require_gmp", "approximate_inverse", "solve_enclosure"}


def signature(value):
    if type(value) is G.mpfr:
        return ["mpfr", G.to_binary(value).hex(), value.precision,
                value.rc, value.is_signed()]
    if isinstance(value, dict):
        return {k: signature(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [signature(v) for v in value]
    return value


def selected_source():
    raw = MAP.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MAP_SHA:
        raise ValueError("Selected source map changed; reassessment required")
    entry = next(e for e in json.loads(raw)["entries"] if e["member"] == MEMBER)
    data = (ROOT / entry["public_path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["public_sha256"]:
        raise ValueError("Selected certificate bytes changed")
    return data.decode("utf-8"), entry


def definitions(source, candidate=False):
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))
             and n.name in NAMES]
    if {n.name for n in nodes} != NAMES:
        raise ValueError("Required numerical definitions missing")
    code = "\n\n".join(ast.get_source_segment(source, n) for n in nodes)
    if candidate:
        old = """xhat = []
    for row in r:
        value = ar.zero
        for v, bound in zip(row, b, strict=True):
            value = ar.near.add(value, ar.near.mul(v, ar.midpoint(bound)))"""
        new = """xhat = []
    midpoint_cache = {}
    for row in r:
        value = ar.zero
        for j, (v, bound) in enumerate(zip(row, b, strict=True)):
            if j not in midpoint_cache:
                midpoint_cache[j] = ar.midpoint(bound)
            value = ar.near.add(value, ar.near.mul(v, midpoint_cache[j]))"""
        if code.count(old) != 1:
            raise ValueError("Midpoint substitution no longer matches")
        code = code.replace(old, new)
        old = "dots = _h3_batch(ar, a, [[(x, x) for x in xhat]])"
        new = "xhat_intervals = [(x, x) for x in xhat]\n    dots = _h3_batch(ar, a, [xhat_intervals])"
        if code.count(old) != 1 or code.count("ar.dot(row, [(x, x) for x in xhat])") != 1:
            raise ValueError("Residual substitution no longer matches")
        code = code.replace(old, new).replace("ar.dot(row, [(x, x) for x in xhat])",
                                             "ar.dot(row, xhat_intervals)")
    namespace = {"G": G, "CancelledError": CancelledError,
                 "_h3_batch": lambda *a, **kw: None}
    exec(compile(code, "<selected-certificate-feasibility>", "exec"), namespace)
    return namespace


def solve(ns, matrix, rhs, precision, cancel_at=None):
    calls, checks = [], []
    ar_type = ns["Arithmetic"]
    midpoint, check = ar_type.midpoint, ar_type.check

    def counted_midpoint(self, bounds):
        calls.append(1)
        return midpoint(self, bounds)

    def counted_check(self, phase):
        checks.append(phase)
        if cancel_at == len(checks):
            raise CancelledError("injected bounded cancellation")
        return check(self, phase)

    ar_type.midpoint, ar_type.check = counted_midpoint, counted_check
    try:
        try:
            bounds, ar, proof = ns["solve_enclosure"](matrix, rhs, precision=precision)
            contexts = [[getattr(c, f) for f in
                         ("inexact", "underflow", "overflow", "invalid", "divzero", "erange")]
                        for c in (ar.down, ar.up, ar.near)]
            outcome = {"bounds": signature(bounds), "proof": signature(proof),
                       "context_flags": contexts}
        except (ns["Unresolved"], ValueError, CancelledError) as error:
            outcome = {"error": type(error).__name__, "reason": str(error)}
        return outcome, len(calls), checks
    finally:
        ar_type.midpoint, ar_type.check = midpoint, check


def dot_signature(ar, x, y):
    return signature(ar.dot(x, y))


def zero_product_dot(ar, left, right):
    """Feasibility only: replace a zero product, never its ordered addition."""
    lo = hi = ar.zero
    for a, b in zip(left, right, strict=True):
        eligible = (type(a) is tuple and type(b) is tuple and len(a) == len(b) == 2
                    and all(type(v) is G.mpfr and G.is_finite(v) for v in (*a, *b))
                    and (all(G.is_zero(v) for v in a) or all(G.is_zero(v) for v in b)))
        if eligible:
            ar.check('interval-product')
            negative = a[0].is_signed() != b[0].is_signed()
            product = G.mpfr('-0.0' if negative else '0.0', ar.down.precision)
            lower = upper = product
        else:
            lower, upper = ar.mul(a, b)
        ar.check('interval-add')
        lo, hi = ar.down.add(lo, lower), ar.up.add(hi, upper)
    return lo, hi


def controls():
    source, entry = selected_source()
    ref, candidate = definitions(source), definitions(source, True)
    cases = []
    for n in (2, 3, 4):
        matrix = [[G.mpq(int(i == j)) for j in range(n)] for i in range(n)]
        matrix += [[G.mpq(j+1, n+3) for j in range(n)]]
        rhs = [G.mpq((-1)**j * (j+1), 7) for j in range(n)]
        for precision in (53, 80, 320):
            a, ac, checks_a = solve(ref, matrix, rhs, precision)
            b, bc, checks_b = solve(candidate, matrix, rhs, precision)
            assert "error" not in a and a == b and checks_a == checks_b
            assert ac == 2*n*n and bc == n*n+n
            cases.append({"rank": n, "observations": len(matrix), "precision": precision,
                          "exact_output_and_flags": True, "same_check_trace": True,
                          "midpoint_calls_reference": ac, "midpoint_calls_candidate": bc,
                          "rhs_midpoint_arithmetic_removed": 2*n*(n-1),
                          "fallback_interval_tuple_constructions_removed": n*n})
    failures = []
    for matrix, rhs, point in (([], [], None), ([[G.mpq(0)]], [G.mpq(1)], None),
                               ([[G.mpq(1), G.mpq(0)], [G.mpq(0), G.mpq(1)]],
                                [G.mpq(1), G.mpq(2)], 1),
                               ([[G.mpq(1), G.mpq(0)], [G.mpq(0), G.mpq(1)]],
                                [G.mpq(1), G.mpq(2)], 10),
                               ([[G.mpq(1), G.mpq(0)], [G.mpq(0), G.mpq(1)]],
                                [G.mpq(1), G.mpq(2)], 50)):
        a, _, ca = solve(ref, matrix, rhs, 53, point)
        b, _, cb = solve(candidate, matrix, rhs, 53, point)
        assert "error" in a and a == b and ca == cb
        failures.append({"cancel_at": point, "outcome": a, "same_check_trace": True})

    ar = ref["Arithmetic"](8)
    z, nz, one, negone = ar.zero, ar.near.minus(ar.zero), ar.one, ar.near.minus(ar.one)
    left, right = [(negone, nz)], [(negone, z)]
    swapped = [dot_signature(ar, left, right), dot_signature(ar, right, left)]
    assert swapped[0] != swapped[1]
    x = [(one, one), ar.point(G.mpq(1, 3)), (z, z)]
    y = [(one, one)]*3
    zero_full, zero_skip = dot_signature(ar, x, y), dot_signature(ar, x[:-1], y[:-1])
    assert zero_full != zero_skip
    # Independent exact-rational sum with just final directed conversion.
    terms = [(one, one), ar.point(G.mpq(1, 3)), ar.point(G.mpq(1, 3))]
    folded = ar.dot(terms, y)
    with ar.down:
        lower = G.mpfr(sum((G.mpq(t[0]) for t in terms), G.mpq(0)))
    with ar.up:
        upper = G.mpfr(sum((G.mpq(t[1]) for t in terms), G.mpq(0)))
    exact_once = lower, upper
    assert tuple(map(G.mpq, folded)) != tuple(map(G.mpq, exact_once))
    refutations = {
        "unconditional_gram_symmetry_changes_zero_sign": swapped,
        "dropping_final_zero_changes_ternary": {"full": zero_full, "skipped": zero_skip},
        "round_once_changes_enclosure": {
            "ordered_fold": [str(G.mpq(v)) for v in folded],
            "exact_then_round": [str(G.mpq(v)) for v in exact_once]}}
    zero_cases = 0
    for precision in (8, 53, 320):
        az = ref['Arithmetic'](precision)
        zero, negzero = az.zero, az.near.minus(az.zero)
        zeros = [(zero, zero), (negzero, negzero), (negzero, zero), (zero, negzero)]
        others = zeros + [az.point(G.mpq(1, 3)), az.point(G.mpq(-2, 7)),
                          (az.near.minus(az.one), az.one),
                          (az.up.mul_2exp(az.one, 600000000), az.up.mul_2exp(az.one, 600000000)),
                          (az.down.mul_2exp(az.one, -600000000), az.down.mul_2exp(az.one, -600000000))]
        for a in zeros:
            for b in others:
                for x, y in ((a, b), (b, a)):
                    lhs = [(az.one, az.one), az.point(G.mpq(1, 3)), x]
                    rhs = [(az.one, az.one), (az.one, az.one), y]
                    before = az.dot(lhs, rhs)
                    after = zero_product_dot(az, lhs, rhs)
                    assert signature(before) == signature(after)
                    zero_cases += 1
    exceptional = []
    for bad in (G.mpfr('inf'), G.mpfr('-inf'), G.mpfr('nan')):
        outcomes = []
        for operation in (lambda: ar.dot([(z, z)], [(bad, bad)]),
                          lambda: zero_product_dot(ar, [(z, z)], [(bad, bad)])):
            try:
                operation()
                raise AssertionError('Exceptional operand did not trap')
            except G.InvalidOperationError as error:
                outcomes.append(type(error).__name__)
        assert outcomes[0] == outcomes[1]
        exceptional.append(outcomes[0])
    prefix_cases = []
    for precision in (53, 320):
        ap = ref['Arithmetic'](precision)
        points = [ap.point(G.mpq(q, 7)) for q in (-5, 0, 3, 9, -2)]
        columns = [points, list(reversed(points)), points[1:]+points[:1]]
        for old_length in (1, 3):
            for left in columns:
                for right in columns:
                    prefix = ap.dot(left[:old_length], right[:old_length])
                    continued = prefix
                    for x, y in zip(left[old_length:], right[old_length:], strict=True):
                        continued = ap.add(continued, ap.mul(x, y))
                    assert signature(continued) == signature(ap.dot(left, right))
            prefix_cases.append({'precision': precision, 'old_observations': old_length,
                                 'new_observations': 5, 'ordered_gram_dots_equal': 9})
    # A broken equality predicate must reject the known zero-sign mutation.
    assert swapped[0] != swapped[1] and zero_full != zero_skip
    return {"schema": "atlas.plan40b.bounded-arithmetic-controls.r1", "status": "PASS",
            "source_map_sha256": MAP_SHA, "selected_member": entry,
            "gmpy2": G.version(), "mpfr": G.mpfr_version(),
            "scope": "AST-selected reference arithmetic; no compiled H3 import or dispatch; no runtime proof or timing",
            "candidate_cases": cases, "refusal_and_cancellation_cases": failures,
            "independent_refutations": refutations,
            "zero_product_specialisation": {"exact_signature_cases": zero_cases,
                "nonfinite_reference_refusals": exceptional,
                "scope": "finite MPFR endpoints; degenerate signed-zero interval; first-corner sign retained; every ordered addition retained",
                "per_eligible_term": {"reference_multiplications": 8, "candidate_multiplications": 0,
                                      "reference_additions": 2, "candidate_additions": 2},
                "production_zero_frequency_measured": False},
            "same_precision_append_only_gram": {"cases": prefix_cases,
                "scope": "Exact existing rounded accumulator continued in original order; no inverse reuse; no native/resource qualification",
                "invalidated_by": ["precision/context change", "changed/reordered prefix", "basis/scale change", "owner close", "source/method change"]},
            "claims": {"production_changed": False, "compiled_route_validated": False,
                       "worker_dispatched": False, "performance_measured": False,
                       "resource_policy_validated": False, "scientific_acceptance": False}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = controls()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "candidate_cases": len(result["candidate_cases"]),
                      "failure_cases": len(result["refusal_and_cancellation_cases"]),
                      "refutations": len(result["independent_refutations"])}))


if __name__ == "__main__":
    main()
