"""Tiny source-bound logical controls; no Atlas imports, workers or timings."""
if not __debug__:
    raise RuntimeError('Control validation requires assertions; do not use Python -O or -OO')

import ast
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[5]
EXPECTED_MAP_SHA256 = "1d1e2c79fe7825e276e2a33f2d5c18fe3157da8ef4b41ab0c3c347bca9295fcf"
map_raw = (ROOT / "tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json").read_bytes()
if hashlib.sha256(map_raw).hexdigest() != EXPECTED_MAP_SHA256:
    raise ValueError("The selected source map differs from the examined generation")
selection = json.loads(map_raw)
entries = {Path(e["member"]).name: e for e in selection["entries"]}
used_sources = {}


def source_tree(name):
    entry = entries[name]
    path = ROOT / entry["public_path"]
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["public_sha256"]
    used_sources[entry["public_path"]] = entry["public_sha256"]
    return ast.parse(raw)


def functions(name, names, namespace):
    tree = source_tree(name)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), name, "exec"), namespace)


namespace = {"exact_library": lambda: SimpleNamespace(mpq=Fraction)}
functions("private_heat_finish_arithmetic_r1.py", {"feasible_scalar"}, namespace)
guard = {}
functions("private_heat_closed_owned_r5.py", {"_equal_arrays", "_reused_certificate"}, guard)


def search(predicate, cache_interior):
    calls = []
    held = {}

    def certificate(theta):
        calls.append(theta)
        return {"passed": bool(predicate(theta)), "theta": theta}

    endpoint = {q: certificate(q) for q in (Fraction(0), Fraction(1))}
    known = {q: cert["passed"] for q, cert in endpoint.items()}

    def admissible(theta):
        if theta in known:
            return known[theta]
        cert = certificate(theta)
        known[theta] = cert["passed"]
        if cache_interior and cert["passed"]:
            held.clear()
            held[theta] = cert
        return cert["passed"]

    try:
        theta, history = namespace["feasible_scalar"](admissible)
    except ValueError:
        return {"refused": True}, calls
    cert = endpoint.get(theta)
    if cert is None:
        cert = held.get(theta) if cache_interior else None
    if cert is None:
        cert = certificate(theta)
    return {"theta": theta, "history": history, "certificate": cert}, calls


rows = []
for name, predicate in (
    ("full", lambda q: True),
    ("interior_third", lambda q: q <= Fraction(1, 3)),
    ("zero_only", lambda q: q == 0),
    ("refused", lambda q: False),
    ("nonmonotone", lambda q: q <= Fraction(1, 4) or Fraction(1, 2) <= q <= Fraction(5, 8)),
):
    base, before = search(predicate, False)
    candidate, after = search(predicate, True)
    assert base == candidate
    rows.append({"case": name, "baseline_certificates": len(before), "candidate_certificates": len(after), "exact_logical_parity": True})

ar = SimpleNamespace(equal=lambda a, b: a == b, check=lambda: None)
theta = Fraction(1, 3)
energy = [Fraction(5, 7), Fraction(6, 7)]
faces = [(0, 1, Fraction(1, 7))]
cert = {"passed": True, "nested": {"value": Fraction(2, 7)}}
reused = (theta, energy, faces, cert)
copied = guard["_reused_certificate"](ar, theta, reused, list(energy), list(faces))
assert copied == cert and copied is not cert and copied["nested"] is cert["nested"]
refusals = 0
for changed_theta, changed_energy, changed_faces in (
    (Fraction(1, 2), energy, faces),
    (theta, energy[:1], faces),
    (theta, [Fraction(1), energy[1]], faces),
    (theta, energy, [(1, 0, faces[0][2])]),
    (theta, energy, [(0, 1, Fraction(2, 7))]),
):
    try:
        guard["_reused_certificate"](ar, changed_theta, reused, changed_energy, changed_faces)
    except ArithmeticError:
        refusals += 1
assert refusals == 5

load_cases = 0
for old, source, powers in (
    ([Fraction(2), Fraction(3)], [Fraction(0), Fraction(0)], []),
    ([Fraction(2, 7), Fraction(3, 11)], [Fraction(5, 13), Fraction(-1, 17)], [(0, Fraction(2, 19)), (1, Fraction(-3, 23))]),
    ([Fraction(2), Fraction(3)], [Fraction(1, 10), Fraction(2, 10)], [(0, Fraction(1, 7)), (0, Fraction(2, 7))]),
):
    baseline_loaded = [e+s for e, s in zip(old, source, strict=True)]
    for i, q in powers:
        baseline_loaded[i] -= q
    baseline_load = [e+s for e, s in zip(old, source, strict=True)]
    candidate_load = [e+s for e, s in zip(old, source, strict=True)]
    candidate_loaded = list(candidate_load)
    for i, q in powers:
        candidate_loaded[i] -= q
    assert (baseline_load, baseline_loaded) == (candidate_load, candidate_loaded)
    assert candidate_load is not candidate_loaded
    load_cases += 1

# Source-extracted cubic basis, with Fraction recording of guard operands.
# This is not a WorkBudget emulator: getter allocations, reserve implementation,
# cancellation and native backend behaviour still need implementation proof.
exponents_tree = source_tree("private_heat_functionals_kernel_r1.py")
exponents_node = next(node for node in exponents_tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "EXPONENTS" for t in node.targets))
polynomial_namespace = {}
exec(compile(ast.Module(body=[exponents_node], type_ignores=[]), "selected-exponents", "exec"), polynomial_namespace)
exponents = polynomial_namespace["EXPONENTS"]
polynomial_namespace["F"] = SimpleNamespace(EXPONENTS=exponents)
basis_tree = source_tree("private_heat_support_basis_resources_r1.py")
basis_class = next(node for node in basis_tree.body if isinstance(node, ast.ClassDef) and node.name == "Basis")
point_node = next(node for node in basis_class.body if isinstance(node, ast.FunctionDef) and node.name == "point")
exec(compile(ast.Module(body=[point_node], type_ignores=[]), "selected-Basis.point", "exec"), polynomial_namespace)
# Bind the actual source of the selected wrapper and exact-growth policy too.
source_tree("private_heat_support_basis_resources_r2.py")
source_tree("private_heat_exact_growth_r1.py")


class PointControl:
    def __init__(self, origin, scale):
        self.origin, self.scale = origin, scale
        self.trace = []
        self.products = 0

    def _vector(self):
        self.trace.append(("vector", 20))

    def q(self, value):
        value = Fraction(value)
        self.trace.append(("q", value))
        return value

    def admit(self, operation, a, b):
        an, ad = max(1, a.numerator.bit_length()), a.denominator.bit_length()
        bn, bd = max(1, b.numerator.bit_length()), b.denominator.bit_length()
        width = {"subtract": max(max(an+bd, bn+ad)+1, ad+bd),
                 "multiply": max(an+bn, ad+bd), "divide": max(an+bd, ad+bn)}[operation]
        self.trace.append((operation, a, b, width))

    def op(self, operation, a, b):
        self.admit(operation, a, b)
        if operation == "multiply":
            self.products += 1
            return a*b
        return a-b if operation == "subtract" else a/b


def point_reuse(control, point):
    """Same guard operands/order; memo key is the symbolic monomial, not value.

    The prototype dict illustrates reuse only. A production implementation must
    account metadata or use static exponent indices into the existing result.
    """
    control._vector()
    coordinate = [control.op("divide", control.op("subtract", control.q(a), b), control.scale)
                  for a, b in zip(point, control.origin, strict=True)]
    zero = (0, 0, 0)
    known = {zero: Fraction(1)}
    for axis, value in enumerate(coordinate):
        known[tuple(int(i == axis) for i in range(3))] = value

    def multiply(a, ae, b, be):
        control.admit("multiply", a, b)
        key = tuple(x+y for x, y in zip(ae, be, strict=True))
        if key not in known:
            control.products += 1
            known[key] = a*b
        return known[key], key

    result = []
    for exponent in exponents:
        product, product_key = control.q(1), zero
        for axis, (value, power) in enumerate(zip(coordinate, exponent, strict=True)):
            factor, factor_key = control.q(1), zero
            axis_key = tuple(int(i == axis) for i in range(3))
            for _ in range(power):
                factor, factor_key = multiply(factor, factor_key, value, axis_key)
            product, product_key = multiply(product, product_key, factor, factor_key)
        result.append(product)
    return result


point_rows = []
for name, point, origin, scale in (
    ("zeros", (0, 0, 0), (0, 0, 0), 1),
    ("mixed_signs", (-3, 5, -7), (1, -2, 4), 8),
    ("large_rationals", (Fraction(2**257+1, 3**91), Fraction(-5**103, 7**83), Fraction(11**79, 13**67)), (0, 1, -1), 2**37),
    ("small_dyadics", (Fraction(1, 2**1074), Fraction(-1, 2**900), 1), (0, 0, 0), Fraction(1, 2**500)),
):
    point, origin, scale = tuple(map(Fraction, point)), tuple(map(Fraction, origin)), Fraction(scale)
    baseline, candidate = PointControl(origin, scale), PointControl(origin, scale)
    before = polynomial_namespace["point"](baseline, point)
    after = point_reuse(candidate, point)
    assert len(before) == len(after) == 20 and before == after
    assert [(q.numerator, q.denominator) for q in before] == [(q.numerator, q.denominator) for q in after]
    assert baseline.trace == candidate.trace
    assert baseline.products == 105 and candidate.products == 16
    point_rows.append({"case": name, "exact_canonical_outputs": 20, "baseline_exact_multiplications": baseline.products,
                       "reused_exact_multiplications": candidate.products, "unchanged_multiply_admissions": 105,
                       "same_guard_operands_order_and_widths": True})

print(json.dumps({
    "status": "PASS",
    "scope": "Source-extracted Fraction logical controls only; no GMP, resource, runtime, performance or scientific qualification",
    "selection": selection["public_selection_sha256"],
    "source_map_sha256": EXPECTED_MAP_SHA256,
    "control_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "sources": used_sources,
    "scalar_search": rows,
    "stale_state_refusals": refusals,
    "load_reuse_cases": load_cases,
    "cubic_point_reuse": point_rows,
    "implementation_limits": [
        "Unimplemented and unmeasured; real GMP guard and resource policy are not exercised",
        "Interior reuse retains one certificate/state; replacement may overlap the previous and new retained generations",
        "Base load reuse extends one n-cell base array lifetime; the boundary-debited mutable array must be distinct",
        "Source-drift refusal, cancellation, failure-frame custody, operation/resource diagnostics and consumer identity need implementation qualification",
        "Cubic control compares exact value and guard operands/order/widths, not real WorkBudget, GMP getters or cancellation",
        "Cubic reuse preserves 105 multiplication admission positions but performs 16 multiplications; actual and reused work must be reported honestly",
    ],
}, indent=2))
