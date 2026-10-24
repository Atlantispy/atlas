"""Bounded Plan40B functional prototypes. No production imports or source edits."""
if not __debug__:
    raise RuntimeError("Optimised Python is refused: correctness assertions required")

import argparse
import ast
from collections import Counter
from concurrent.futures import CancelledError
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal
import decimal
from fractions import Fraction
import gc
from hashlib import sha256
from heapq import nsmallest
import json
import math
from pathlib import Path
import struct
import sys
from time import perf_counter
from types import ModuleType, SimpleNamespace
import weakref

import gmpy2 as G
import psutil

HERE = Path(__file__).resolve().parent
bootstrap = argparse.ArgumentParser(add_help=False)
bootstrap.add_argument("--repo", required=True, type=Path)
bootstrap.add_argument("--private-helpers", type=Path)
bootstrap_args, _ = bootstrap.parse_known_args()
ROOT = bootstrap_args.repo.resolve()
MAP_SHA = "1d1e2c79fe7825e276e2a33f2d5c18fe3157da8ef4b41ab0c3c347bca9295fcf"
raw = (ROOT / "tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json").read_bytes()
if sha256(raw).hexdigest() != MAP_SHA:
    raise ValueError("Selected map changed")
entries = {Path(v["member"]).name: v for v in json.loads(raw)["entries"]}
bindings = {}


def source(name):
    entry = entries[name]
    path = ROOT / entry["public_path"]
    value = path.read_bytes()
    if sha256(value).hexdigest() != entry["public_sha256"]:
        raise ValueError("Selected source changed: " + name)
    bindings[entry["public_path"]] = entry["public_sha256"]
    return path, value.decode("utf-8")


def module(name, names=None, namespace=None, alias=None):
    path, text = source(name)
    out = ModuleType(alias or name[:-3])
    out.__dict__.update(namespace or {})
    out.__file__ = str(path)
    sys.modules[out.__name__] = out
    if names is None:
        tree = ast.parse(text)
    else:
        tree = ast.parse(text)
        keep = []
        for node in tree.body:
            declared = ([node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
                        [n.id for n in node.targets if isinstance(n, ast.Name)] if isinstance(node, ast.Assign) else [])
            if set(declared) & set(names):
                keep.append(node)
        tree = ast.Module(body=keep, type_ignores=[])
    exec(compile(tree, str(path), "exec"), out.__dict__)
    return out


package = ModuleType("atlas_tectonics")
package.__path__ = []
sys.modules[package.__name__] = package
budget_module = module("resources.py", alias="atlas_tectonics.resources")
transport = module("integration_spatial_transport.py", {"_EscapingWorkspace", "_preserve_workspace"},
                   {"weakref": weakref}, "atlas_tectonics.integration_spatial_transport")
R = module("private_heat_gmp_resources_r1.py")
I = module("private_heat_interval_inventory_r1.py", {"Shape", "add_shape", "multiply_shape"},
           {"dataclass": dataclass})
E = module("private_heat_exact_growth_r1.py")
P = module("private_heat_decimal_sparse_core_r1.py", {"OwnedSolve"})
D = module("private_heat_decimal_inventory_r1.py",
           {"HERE", "CORE_SHA256", "POLICY_SHA256", "POLICY_PATH", "CONTAINER_UNIT", "_check", "_sha", "_runtime"},
           {"Path": Path, "D": Decimal, "decimal": decimal, "struct": struct, "sys": sys,
            "sha256": sha256, "P": P, "CancelledError": CancelledError})
C = module("private_heat_certification_resources_r1.py", {"HERE", "PINS", "check", "size", "verify_sources"},
           {"Path": Path, "sys": sys, "sha256": sha256, "D": D, "CancelledError": CancelledError})
F = module("private_heat_functionals_kernel_r1.py",
           {"EXPONENTS", "decode", "vector", "dot", "sub", "cross", "face_second_moment", "_parts",
            "_float_le_rational", "_rational_le_float", "_enclosure", "_down_nonnegative", "_distance_lower",
            "_upper_cutoff", "_exact_distance", "ScreenedSupport", "nearest_complete_shell"},
           {"Q": Fraction, "G": G, "index": __import__("operator").index, "isfinite": math.isfinite,
            "nextafter": math.nextafter, "inf": math.inf, "sys": sys, "nsmallest": nsmallest,
            "CancelledError": CancelledError})
L = module("private_heat_low_ledger_inventory_r1.py",
           {"CONTAINER_UNIT", "ZERO", "PUBLIC_BINARY64", "_NO_INLINE", "_INLINE_RESOURCES_SHA256", "_FRACTION_ZERO_SIZE",
            "_inline_checked", "_inline_resources", "_py_int", "_check", "_size", "RationalGrowth"},
           {"D": D, "I": I, "sys": sys, "Path": Path, "sha256": sha256, "Decimal": Decimal,
            "Fraction": Fraction, "math": math, "CancelledError": CancelledError})
B1 = module("private_heat_support_basis_resources_r1.py", {"FUNCTIONALS_SHA", "_verify", "_coordinate", "Basis"},
            {"F": F, "G": G, "I": C, "E": E, "P": P, "L": L, "Fraction": Fraction,
             "sys": sys, "Path": Path, "sha256": sha256})
B2 = module("private_heat_support_basis_resources_r2.py", {"Basis"}, {"B": B1, "sys": sys})
B2.B = B1
PREP = module("private_heat_functionals_kernel_r5.py", {"_prepare"},
              {"I": C, "E": E, "B": B2, "P": P, "G": G, "Fraction": Fraction, "sys": sys})

# Keep the selected rational admission prefix intact, replacing only execution.
_, growth_text = source("private_heat_exact_growth_r1.py")
growth_tree = ast.parse(growth_text)
growth_class = next(n for n in growth_tree.body if isinstance(n, ast.ClassDef) and n.name == "Arithmetic")
guard_node = next(n for n in growth_class.body if isinstance(n, ast.FunctionDef) and n.name == "rational")
guard_node.name = "admit_only"
cut = next(i for i, n in enumerate(guard_node.body) if isinstance(n, ast.AugAssign)
           and isinstance(n.target, ast.Attribute) and n.target.attr == "operations")
guard_node.body = guard_node.body[:cut+1] + [ast.Return(value=ast.Constant(None))]
guard_namespace = dict(E.__dict__)
exec(compile(ast.fix_missing_locations(ast.Module(body=[guard_node], type_ignores=[])),
             "selected-rational-admission-prefix", "exec"), guard_namespace)


def canonical(value):
    if type(value) in (G.mpq, Fraction):
        return (int(value.numerator), int(value.denominator))
    if type(value) in (G.mpz, int):
        return (int(value), 1)
    return value


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class Poll:
    def __init__(self, at=None):
        self.at, self.calls = at, 0

    def __call__(self):
        self.calls += 1
        return self.calls == self.at


class TraceArithmetic(E.Arithmetic):
    def __init__(self, *args, **kwargs):
        self.trace, self.executed, self.hits = [], Counter(), Counter()
        super().__init__(*args, **kwargs)

    def reserve(self, bits):
        self.trace.append(("reserve", bits, self.slots, self.containers))
        return super().reserve(bits)

    def rational(self, operation, a, b):
        self.trace.append((operation, canonical(a), canonical(b)))
        result = super().rational(operation, a, b)
        self.executed[operation] += 1
        return result

    def reused(self, operation, a, b, cache, key):
        self.trace.append((operation, canonical(a), canonical(b)))
        guard_namespace["admit_only"](self, operation, a, b)
        if key not in cache:
            cache[key] = {"multiply": lambda: a*b, "divide": lambda: a/b,
                          "add": lambda: a+b}[operation]()
            self.executed[operation] += 1
        else:
            self.hits[operation] += 1
        return cache[key]


def point_candidate(builder, point, cache):
    builder._vector()
    coordinate = [builder.op("divide", builder.op("subtract", builder.q(a), b), builder.scale)
                  for a, b in zip(point, builder.origin, strict=True)]
    zero = (0, 0, 0)
    cache[zero] = G.mpq(1)
    for i, value in enumerate(coordinate):
        cache[tuple(int(i == j) for j in range(3))] = value
    result = []
    for exponent in F.EXPONENTS:
        product, pe = builder.q(1), zero
        for axis, (value, power) in enumerate(zip(coordinate, exponent, strict=True)):
            factor, fe = builder.q(1), zero
            unit = tuple(int(axis == j) for j in range(3))
            for _ in range(power):
                key = tuple(x+y for x, y in zip(fe, unit, strict=True))
                factor = builder.arena.reused("multiply", factor, value, cache, key)
                fe = key
            key = tuple(x+y for x, y in zip(pe, fe, strict=True))
            product = builder.arena.reused("multiply", product, factor, cache, key)
            pe = key
        result.append(product)
    return result


def flux_candidate(builder, face, normal, moment, conductivity, cache):
    builder._vector()
    mean = [builder.op("divide", builder.op("subtract", builder.q(a), b), builder.scale)
            for a, b in zip(face, builder.origin, strict=True)]
    def reuse(op, a, b, key):
        return builder.arena.reused(op, a, b, cache, key)
    def average(exponent):
        indices = [i for i, power in enumerate(exponent) for _ in range(power)]
        if not indices:
            return builder.q(1)
        if len(indices) == 1:
            return mean[indices[0]]
        i, j = indices
        product = reuse("multiply", mean[i], mean[j], ("product", i, j))
        value = builder.q(moment[i][j])
        square = reuse("multiply", builder.scale, builder.scale, ("scale",))
        quotient = reuse("divide", value, square, ("moment", i, j))
        return reuse("add", product, quotient, ("average", i, j))
    return [builder.op("multiply", -builder.q(conductivity), builder.total(
        builder.op("divide", builder.op("multiply",
            reuse("multiply", builder.q(normal[j]), power, ("normal", j, power)),
            average(tuple(p-int(i == j) for i, p in enumerate(exponent)))), builder.scale)
        for j, power in enumerate(exponent) if power)) for exponent in F.EXPONENTS]


POINTS = [((0, 0, 0), (0, 0, 0), G.mpq(1)),
          ((-3, 5, -7), (1, -2, 4), G.mpq(8)),
          ((G.mpq(2**257+1, 3**91), G.mpq(-5**103, 7**83), G.mpq(11**79, 13**67)),
           (0, 1, -1), G.mpq(2**37)),
          ((G.mpq(1, 2**1074), G.mpq(-1, 2**900), 1), (0, 0, 0), G.mpq(1, 2**500))]
FLUX_NORMAL = tuple(map(G.mpq, (3, -5, 7)))
FLUX_MOMENT = tuple(tuple(G.mpq(i+j+1, (i+1)*(j+1)*7) for j in range(3)) for i in range(3))
FLUX_K = G.mpq(11, 13)


def run_basis(candidate_id, index, candidate, *, limit=256 << 20, cancel_at=None, force_fallback=False):
    budget = budget_module.WorkBudget(limit)
    poll = Poll(cancel_at)
    work = R.OwnedWorkspace(budget, 262144, cancelled=poll)
    work.__enter__()
    optional = None
    arena = builder = result = None
    cached = False
    cache = {}
    error_record = None
    try:
        arena = TraceArithmetic(work, G, scalar_slots=128, container_bytes=262144,
                                initial_bits=2200, cancelled=poll)
        builder = B2.Basis.__new__(B2.Basis)
        point, origin, scale = POINTS[index]
        builder.arena, builder.vectors = arena, 0
        builder.origin, builder.scale = tuple(map(G.mpq, origin)), scale
        values = (*point, *origin, scale)
        # Conservative explicit optional cache funding, BEFORE cache population.
        # Existing arithmetic envelope remains charged and retains all its checks.
        width = 16*max(8*sys.getsizeof(v) for v in values)
        optional_bytes = 131072+128*R.native_slot_allowance(R.RationalShape(width, width))
        future_reference = 262144+24*1024+212*R.native_slot_allowance(R.RationalShape(width, width))
        future_reference += R.native_workspace_allowance(8*width, 212)
        if candidate and not force_fallback and budget.available_bytes >= optional_bytes+future_reference:
            optional = R.OwnedWorkspace(budget, optional_bytes, category="prototype-funded-cache")
            optional.__enter__()
            cached = True
        if candidate_id == "C1":
            result = point_candidate(builder, point, cache) if cached else builder.point(point)
        else:
            arguments = (point, FLUX_NORMAL, FLUX_MOMENT, FLUX_K)
            result = flux_candidate(builder, *arguments, cache) if cached else builder.flux(*arguments)
        output = [canonical(q) for q in result]
        # Cache scalar storage is explicitly bounded; count aliases per occurrence.
        observed_bytes = sum(sys.getsizeof(k)+sum(sys.getsizeof(p) for p in k)+sys.getsizeof(v)
                             for k, v in cache.items())+sys.getsizeof(cache)
        if optional is not None:
            assert observed_bytes <= optional.lease.count
        report = {"outcome": "success", "values": output, "digest": digest(output),
                  "executed": dict(arena.executed), "reused": dict(arena.hits),
                  "logical_operations": arena.operations, "guard_trace": digest(arena.trace),
                  "trace_rows": arena.trace,
                  "polls": poll.calls, "cache_entries": len(cache), "cache_enabled": cached,
                  "cache_charged_bytes": 0 if optional is None else optional.lease.count,
                  "cache_observed_object_bytes": observed_bytes,
                  "reference_lease_bytes": work.lease.count, "peak_reserved_bytes": budget.peak_reserved_bytes}
    except (CancelledError, budget_module.MemoryLimitError, ValueError, TypeError) as error:
        # Exercise native escaping ownership, keep the error alive long enough to observe the charge.
        error_record = error
        try:
            work.__exit__(type(error), error, error.__traceback__)
        except BaseException:
            pass
        if optional is not None:
            try:
                optional.__exit__(type(error), error, error.__traceback__)
            except BaseException:
                pass
            optional = None
        report = {"outcome": type(error).__name__, "message": str(error), "polls": poll.calls,
                  "guard_trace": digest(arena.trace) if arena else None,
                  "retained_while_error_alive": budget.reserved_bytes,
                  "cache_enabled": cached}
    finally:
        result = builder = arena = None
        cache.clear()
        if optional is not None:
            optional.__exit__(None, None, None)
        if not work.finished:
            work.__exit__(None, None, None)
        work = None
    if error_record is not None:
        error_record.__traceback__ = None
        error_record = None
        gc.collect()
    report["reserved_after_drop"] = budget.reserved_bytes
    assert report["reserved_after_drop"] == 0, report
    return report


def basis_tests(candidate_id):
    rows = []
    for index in range(len(POINTS)):
        before, after = run_basis(candidate_id, index, False), run_basis(candidate_id, index, True)
        assert before["outcome"] == after["outcome"] == "success"
        assert before["values"] == after["values"]
        for key in ("guard_trace", "logical_operations", "polls", "reference_lease_bytes"):
            assert before[key] == after[key], (candidate_id, index, key, next(
                ((i, a, b) for i, (a, b) in enumerate(zip(before["trace_rows"], after["trace_rows"], strict=False)) if a != b), None))
        before.pop("trace_rows")
        after.pop("trace_rows")
        assert after["cache_enabled"]
        assert before["executed"]["multiply"] == (105 if candidate_id == "C1" else 116)
        assert after["executed"]["multiply"] == (16 if candidate_id == "C1" else 66)
        fallback = run_basis(candidate_id, index, True, force_fallback=True)
        assert fallback["digest"] == before["digest"] and fallback["executed"] == before["executed"]
        rows.append({"fixture": index, "baseline": before, "candidate": after,
                     "unfunded_cache_reference_fallback": True})
    faults = []
    total = rows[0]["baseline"]["polls"]
    for at in (10, 30, total//2, total-1):
        before = run_basis(candidate_id, 0, False, cancel_at=at)
        after = run_basis(candidate_id, 0, True, cancel_at=at)
        assert before["outcome"] == after["outcome"] == "CancelledError"
        assert before["guard_trace"] == after["guard_trace"] and before["polls"] == after["polls"]
        faults.append({"cancel_at": at, "baseline": before, "candidate": after})
    # Test initial-envelope refusal and a one-byte-short vector-growth reservation.
    for limit in (2700000, rows[0]["baseline"]["reference_lease_bytes"]-1):
        before, after = run_basis(candidate_id, 0, False, limit=limit), run_basis(candidate_id, 0, True, limit=limit)
        assert before["outcome"] == after["outcome"]
        faults.append({"budget": limit, "baseline": before, "candidate": after})
    return {"status": "PASS_NATIVE_GMP_AND_ACCOUNTED_SEAM", "cases": rows, "faults": faults,
            "limits": ["Source-extracted method invocation, not production import/complete face qualification",
                       "Optional cache bound is conservative for these fixed operands; no arbitrary-input/RSS theorem",
                       "No worker execution, timing or scientific qualification"]}


def encode(values):
    return [[format(Fraction(v).numerator, "x"), format(Fraction(v).denominator, "x")] for v in values]


def prepared_tests():
    payload = {"cells": [{"cell_id": "c", "centroid_m": encode((0, 0, 0)), "faces": [("f", 1)]}],
               "faces": [{"face_id": "f", "centroid_m": encode((1, 0, 0)),
                          "area_vector_m2": encode((1, 0, 0)), "owners": ["c"]}]}
    rows = []
    # Actual selected entry and source fence are retained. Sanitised runtime policy is intentionally not replaced.
    for name, item, walls, powers, at in (
        ("valid_geometry_source_fence", payload, ["f"], [], None),
        ("bad_payload", {}, ["f"], [], None),
        ("bad_partition_type", payload, "f", [], None),
        ("cancelled_preparation", payload, ["f"], [], 1),
    ):
        budget = budget_module.WorkBudget(64 << 20)
        try:
            owner = PREP._prepare(item, walls, powers, 1, budget=budget, cancelled=Poll(at))
        except BaseException as error:
            message = ("Sanitised private policy path is absent" if isinstance(error, FileNotFoundError) else str(error))
            rows.append({"case": name, "outcome": type(error).__name__, "message": message,
                         "charged_while_error_alive": budget.reserved_bytes})
            error.__traceback__ = None
        else:
            owner.close()
            raise AssertionError("Unexpected selected runtime-fence admission")
        gc.collect()
    # A cache cannot be populated from a refused preparation. Exercise this literal fail-closed boundary.
    assert rows[0]["outcome"] in (RuntimeError.__name__, FileNotFoundError.__name__)
    if bootstrap_args.private_helpers is None:
        return {"status": "PARTIAL_ENTRY_REFUSAL_GAP", "entry_cases": rows,
            "candidate_populated": False, "baseline_candidate": "Both retain source-fence refusal; no cache bypass",
            "gap": "Selected public _prepare -> Basis._verify -> certification.verify_sources -> Decimal._runtime requires private pinned runtime/policy; no admitted preparation owner exists here. Valid cached preparation, stale numerical inputs after admission and actual serial/worker retention cannot be claimed tested.",
            "workload_sha256": digest(payload)}
    prepare, component_fence, private_dependency = preparation_component()
    return prepared_cache_tests(payload, rows, prepare, component_fence, private_dependency)


def preparation_component():
    if bootstrap_args.private_helpers is None:
        raise ValueError("C2 component requires --private-helpers")
    # Explicit component dependency injection: original private Decimal runtime source,
    # verified against the map's original hash. No public helper/fence is overwritten.
    private_path = bootstrap_args.private_helpers / "private_heat_decimal_inventory_r1.py"
    private_bytes = private_path.read_bytes()
    expected = entries[private_path.name]["original_sha256"]
    if sha256(private_bytes).hexdigest() != expected:
        raise ValueError("Private Decimal dependency differs from selected original")
    private_names = {"HERE", "CORE_SHA256", "POLICY_SHA256", "POLICY_PATH", "CONTAINER_UNIT", "_check", "_sha", "_runtime"}
    private_namespace = dict(D.__dict__)
    private_namespace["__file__"] = str(private_path)
    nodes = []
    for node in ast.parse(private_bytes).body:
        declared = ([node.name] if isinstance(node, ast.FunctionDef) else
                    [n.id for n in node.targets if isinstance(n, ast.Name)] if isinstance(node, ast.Assign) else [])
        if set(declared) & private_names:
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "private-pinned-decimal-runtime", "exec"), private_namespace)
    private_namespace["_runtime"](None)
    def component_fence(cancel):
        C.check(cancel)
        for member in ("private_heat_functionals_kernel_r5.py", "private_heat_functionals_kernel_r1.py",
                       "private_heat_support_basis_resources_r1.py", "private_heat_exact_growth_r1.py",
                       "private_heat_gmp_resources_r1.py", "resources.py"):
            source(member)
        if sha256(private_path.read_bytes()).hexdigest() != expected:
            raise ValueError("Private Decimal dependency changed")
        private_namespace["_runtime"](cancel)
    injected_check = SimpleNamespace(check=C.check, size=C.size, verify_sources=component_fence)
    bridge = module("private_heat_support_basis_resources_r1.py", {"FUNCTIONALS_SHA", "_verify", "_coordinate"},
                    {"F": F, "G": G, "I": injected_check, "sys": sys, "Fraction": Fraction,
                     "Path": Path, "sha256": sha256}, alias="functional_basis_dependency_bridge")
    prepare = module("private_heat_functionals_kernel_r5.py", {"_prepare"},
                     {"I": C, "E": E, "B": SimpleNamespace(B=bridge), "P": P, "G": G,
                      "Fraction": Fraction, "sys": sys}, alias="functional_prepare_dependency_injection")
    return prepare, component_fence, {"member": private_path.name, "original_sha256": expected,
                                      "policy_sha256": private_namespace["POLICY_SHA256"]}


def freeze(value):
    if isinstance(value, dict):
        return ("dict", tuple(sorted(((freeze(k), freeze(v)) for k, v in value.items()), key=repr)))
    if isinstance(value, (tuple, list, set, frozenset)):
        values = [freeze(v) for v in value]
        return (type(value).__name__, tuple(sorted(values, key=repr) if isinstance(value, (set, frozenset)) else values))
    return (type(value).__name__, canonical(value))


def prepared_cache_tests(payload, rows, prepare, component_fence, private_dependency):
    budget = budget_module.WorkBudget(64 << 20)
    cache_workspace = R.OwnedWorkspace(budget, 131072, category="prototype-prepared-generation")
    cache_workspace.__enter__()
    held, identity, snapshot = None, None, None
    misses = hits = 0
    def borrow(data, walls, powers, k=1, cancel=None):
        nonlocal held, identity, snapshot, misses, hits
        C.check(cancel)
        component_fence(cancel)
        key = freeze((data, walls, powers, k))
        assert len(repr(key)) < 16000  # explicit bounded fixture metadata, not a general cache policy
        if held is not None and key == identity and freeze(held.value) == snapshot:
            hits += 1
            return held.value
        replacement = prepare._prepare(data, walls, powers, k, budget=budget, cancelled=cancel)
        previous, held = held, replacement
        identity, snapshot = key, freeze(held.value)
        misses += 1
        if previous is not None:
            previous.close()
        return held.value
    def baseline(data, walls, powers, k=1):
        original = prepare._prepare(data, walls, powers, k, budget=budget, cancelled=None)
        value = freeze(original.value)
        original.close()
        return value
    cases = []
    for name, data, walls, powers, k in (
        ("first", payload, ["f"], [], 1), ("identical", payload, ["f"], [], 1),
        ("conductivity_changed", payload, ["f"], [], 2),
        ("boundary_partition_changed", payload, [], ["f"], 2),
    ):
        reference = baseline(data, walls, powers, k)
        candidate = freeze(borrow(data, walls, powers, k))
        assert reference == candidate
        cases.append({"case": name, "baseline_digest": digest(reference), "candidate_digest": digest(candidate)})
    changed = json.loads(json.dumps(payload))
    changed["faces"][0]["centroid_m"] = encode((2, 0, 0))
    assert baseline(changed, [], ["f"], 2) == freeze(borrow(changed, [], ["f"], 2))
    held.value["conductivity"] = G.mpq(999)
    assert baseline(changed, [], ["f"], 2) == freeze(borrow(changed, [], ["f"], 2))
    previous_charge = budget.reserved_bytes
    try:
        borrow(changed, [], ["f"], 2, Poll(1))
    except CancelledError:
        pass
    else:
        raise AssertionError("Cached preparation cancellation ignored")
    assert budget.reserved_bytes == previous_charge
    try:
        borrow(changed, ["missing"], [], 2)
    except ValueError as error:
        error.__traceback__ = None
    else:
        raise AssertionError("Invalid replacement preparation accepted")
    gc.collect()
    assert budget.reserved_bytes == previous_charge
    assert held is not None and hits == 1 and misses == 5
    final_owner = held
    held.close()
    held = identity = snapshot = None
    cache_workspace.__exit__(None, None, None)
    assert budget.reserved_bytes == 0
    try:
        final_owner.value
    except RuntimeError:
        pass
    else:
        raise AssertionError("Closed prepared owner borrowed")
    return {"status": "PASS_COMPONENT_DEPENDENCY_INJECTION_PARTIAL_RUNTIME", "entry_cases": rows,
            "component_cases": cases, "cache_hits": hits, "preparations_executed": misses,
            "changed_geometry_reprepared": True, "mutated_cached_output_reprepared": True,
            "cancelled_hit_preserves_owner": True, "failed_replacement_preserves_owner": True,
            "closed_owner_refused": True, "peak_reserved_bytes": budget.peak_reserved_bytes,
            "reserved_after_close": budget.reserved_bytes, "workload_sha256": digest(payload),
            "private_dependency": private_dependency,
            "limits": ["Full selected _prepare body, actual selected converter/arithmetic/native WorkBudget and original private Decimal runtime checker",
                       "Explicit component source-fence dependency injection; not a composed private/public production import qualification",
                       "No complete forward/refinement face certificate or worker lifetime test; no same-face basis/shell retention implementation",
                       "Cache metadata bound is fixture-specific; no general arbitrary-input retained-layout proof"]}


class EnclosureOwner:
    """Prototype table on actual native workspace; not a production/worker owner."""
    def __init__(self, points, budget):
        self.identity = tuple((key, tuple((type(v).__name__, canonical(v)) for v in point)) for key, point in points)
        self.workspace = R.OwnedWorkspace(budget, 1024*(20*len(points)+64), category="prototype-enclosures")
        self.workspace.__enter__()
        self.values = {}
        self.hits = self.misses = 0

    def bind(self, points):
        if self.workspace is None:
            raise RuntimeError("Enclosure owner closed")
        identity = tuple((key, tuple((type(v).__name__, canonical(v)) for v in point)) for key, point in points)
        if identity != self.identity:
            return SimpleNamespace(get=lambda index, axis, value: F._enclosure(value))
        return self

    def get(self, index, axis, value):
        if self.workspace is None:
            raise RuntimeError("Enclosure owner closed")
        if (type(value).__name__, canonical(value)) != self.identity[index][1][axis]:
            raise ValueError("Stale enclosure coordinate generation")
        key = (index, axis)
        if key not in self.values:
            self.values[key] = F._enclosure(value)
            self.misses += 1
        else:
            self.hits += 1
        return self.values[key]

    def close(self):
        self.values.clear()
        if self.workspace is not None:
            self.workspace.__exit__(None, None, None)
            self.workspace = None


_, functionals_text = source("private_heat_functionals_kernel_r1.py")
screen_class = next(n for n in ast.parse(functionals_text).body if isinstance(n, ast.ClassDef) and n.name == "ScreenedSupport")
screen_source = ast.get_source_segment(functionals_text, screen_class)
screen_source = screen_source.replace("def __init__(self, observations, centre, minimum, cancelled):",
                                    "def __init__(self, observations, centre, minimum, cancelled, cache):")
screen_source = screen_source.replace("for _, point in self._points:\n            self._check()",
                                    "for point_index, (_, point) in enumerate(self._points):\n            self._check()")
screen_source = screen_source.replace("for value in point:\n                bounds, uncertain = _enclosure(value)",
                                    "for axis, value in enumerate(point):\n                bounds, uncertain = cache.get(point_index, axis, value)")
screen_source = screen_source.replace("        self._check()\n        centre_intervals = []",
                                    "        self._check()\n        cache = cache.bind(self._points)\n        centre_intervals = []")
screen_namespace = dict(F.__dict__)
exec(compile(screen_source, "selected-screen-with-explicit-cache-seam", "exec"), screen_namespace)
CachedScreen = screen_namespace["ScreenedSupport"]


def enclosure_tests():
    points = [(('cell', i), tuple(map(G.mpq, (i % 5-2, i//5-2, (i*i) % 3)))) for i in range(25)]
    points += [(('wall', 'overflow'), (G.mpq(2**2048), G.mpq(0), G.mpq(0))),
               (('power', 'subnormal'), (G.mpq(1, 2**1075), G.mpq(-1, 2**1075), G.mpq(0)))]
    budget = budget_module.WorkBudget(8 << 20)
    owner = EnclosureOwner(points, budget)
    rows = []
    for centre in ((0, 0, 0), (2, -1, 0), (-1, 2, 1)):
        a, b = Poll(), Poll()
        baseline = F.ScreenedSupport(points, centre, 6, a)
        candidate = CachedScreen(points, centre, 6, b, owner)
        assert baseline.shell == candidate.shell and baseline.diagnostics == candidate.diagnostics
        assert baseline.full_ranking() == candidate.full_ranking()
        assert baseline.diagnostics == candidate.diagnostics and a.calls == b.calls
        rows.append({"centre": centre, "digest": digest(candidate.full_ranking()),
                     "polls": a.calls, "diagnostics": candidate.diagnostics})
    assert owner.misses == 3*len(points) and owner.hits == 6*len(points)
    faults = []
    for at in (1, 3, 10):
        results = []
        for which in (False, True):
            try:
                (CachedScreen(points, (0, 0, 0), 6, Poll(at), owner) if which
                 else F.ScreenedSupport(points, (0, 0, 0), 6, Poll(at)))
            except CancelledError as error:
                results.append((type(error).__name__, str(error)))
        assert len(results) == 2 and results[0] == results[1]
        faults.append({"cancel_at": at, "same_refusal": True})
    stale = list(points)
    stale[0] = (stale[0][0], (G.mpq(99), *stale[0][1][1:]))
    for changed in (stale, list(reversed(points)), [(('cell', 999), points[0][1])]+points[1:]):
        misses, hits = owner.misses, owner.hits
        reference = F.ScreenedSupport(changed, (0, 0, 0), 6, None)
        fallback = CachedScreen(changed, (0, 0, 0), 6, None, owner)
        assert reference.full_ranking() == fallback.full_ranking()
        assert reference.diagnostics == fallback.diagnostics
        assert (misses, hits) == (owner.misses, owner.hits)
    for (i, axis), (bounds, uncertain) in owner.values.items():
        original_bounds, original_uncertain = F._enclosure(points[i][1][axis])
        assert tuple(v.hex() for v in bounds) == tuple(v.hex() for v in original_bounds)
        assert uncertain == original_uncertain
    retained = budget.reserved_bytes
    assert retained > 0
    owner.close()
    assert budget.reserved_bytes == 0
    try:
        owner.get(0, 0, points[0][1][0])
    except RuntimeError:
        pass
    else:
        raise AssertionError("Closed owner borrowed")
    return {"status": "PASS_SERIAL_SOURCE_EXTRACTED_SCREEN_PARTIAL_WRAPPER", "cases": rows,
            "baseline_observation_enclosures": 9*len(points), "candidate_observation_enclosures": 3*len(points),
            "faults": faults, "stale_coordinate_order_key_reference_fallback": True, "closed_borrow_refused": True,
            "retained_owner_bytes": retained, "reserved_after_close": budget.reserved_bytes,
            "workload_sha256": digest(points),
            "limits": ["Actual ScreenedSupport numerical entry with original checks; full support wrapper source fence remains unqualified",
                       "Prototype owner uses real WorkBudget/OwnedWorkspace; worker lifetime/replay is not exercised",
                       "Typed coordinate/order/key mismatches use the unchanged reference numerical screen"]}


def polygon_tests():
    # Reuse accepted numerical fixtures without rerunning or editing them. New test is the unchanged prospective plan.
    public = ROOT / "tectonics/optimisation/workbench/plan40/heat"
    old_raw = (public / "EXTENSION-FLUX-RESULTS.json").read_bytes()
    if sha256(old_raw).hexdigest() != "c3b61d5fc91f53376a4c3c82a41a16992796233b489e90143639cf4e02dd4f1d":
        raise ValueError("Accepted polygon evidence changed")
    old = json.loads(old_raw)
    if old["source_map_sha256"] != MAP_SHA or old["script_sha256"] != sha256((public / "extension_flux_controls.py").read_bytes()).hexdigest():
        raise ValueError("Retained polygon source/control identity changed")
    M = module("private_heat_polygon_moment_inventory_r1.py", {"ONE", "MomentPlan", "_Growth", "_plan", "_hex_shape"},
               {"I": I, "L": L, "START": SimpleNamespace(_size=C.size), "dataclass": dataclass})
    face = {"vertices_m": [encode(p) for p in ((-2, -1, 0), (2, -1, 0), (2, 1, 0), (-2, 1, 0))],
            "centroid_m": encode((0, 0, 0)), "area_vector_m2": encode((0, 0, 8))}
    plans = []
    metadata = 262144+1024*(100*len(face["vertices_m"])+512)
    for _ in range(2):
        metadata_budget = budget_module.WorkBudget(64 << 20)
        with R.OwnedWorkspace(metadata_budget, metadata):
            plan = M._plan(face, metadata, M._Growth(G, R, None))
        plans.append(plan)
    assert plans[0] == plans[1]
    budget = budget_module.WorkBudget(plans[0].total_bytes)
    work = R.OwnedWorkspace(budget, plans[0].total_bytes)
    work.__enter__()
    value = F.face_second_moment(face)
    work.resize_before_allocation_or_after_drop(plans[0].retained_bytes)
    owner = P.OwnedSolve(value, work)
    assert owner.value == value and budget.reserved_bytes == plans[0].retained_bytes
    value = None
    owner.close()
    assert budget.reserved_bytes == 0
    try:
        owner.value
    except RuntimeError:
        pass
    else:
        raise AssertionError("Closed moment owner borrowed")
    failures = []
    for candidate in (False, True):
        small = budget_module.WorkBudget(plans[0].total_bytes-1)
        try:
            with R.OwnedWorkspace(small, plans[0].total_bytes):
                raise AssertionError("Unfunded moment calculation reached")
        except budget_module.MemoryLimitError as error:
            failures.append(str(error))
        assert small.reserved_bytes == 0
    assert failures[0] == failures[1]
    cancel = Poll(7)
    try:
        M._plan(face, 262144, M._Growth(G, R, cancel))
    except CancelledError:
        pass
    else:
        raise AssertionError("Prospective cancellation ignored")
    return {"status": "PASS_UNCHANGED_PLAN_AND_NATIVE_OWNERSHIP_PARTIAL_RUNTIME",
            "reused_numerical_result_sha256": sha256(old_raw).hexdigest(), "retained_result_status": old.get("status"),
            "unchanged_plan_bytes": plans[0].total_bytes, "retained_bytes": plans[0].retained_bytes,
            "planned_operations": plans[0].scalar_operations, "tight_budget_refusals_equal": True,
            "cancel_at": cancel.calls, "closed_borrow_refused": True, "reserved_after_close": budget.reserved_bytes,
            "limits": ["No duplicate numerical fixtures; accepted source-bound four accepted/seven refused results reused",
                       "Optional triangle-sum container layout still needs complete admission; subset does not use it",
                       "Actual full MOMENT runtime source fence/retention-r4 consumer not qualified here"]}


class Phases:
    """Smoke takes identical branches except clock reads and timing fields."""
    def __init__(self, timed):
        self.timed, self.seconds = timed, {}
        self.start = perf_counter() if timed else None

    def mark(self, name):
        if self.timed:
            end = perf_counter()
            self.seconds[name] = end-self.start
            self.start = end


def preparation_fixture():
    return {"cells": [{"cell_id": "c", "centroid_m": encode((0, 0, 0)), "faces": [("f", 1)]}],
            "faces": [{"face_id": "f", "centroid_m": encode((1, 0, 0)),
                       "area_vector_m2": encode((1, 0, 0)), "owners": ["c"]}]}


def run_preparation(candidate, context, timed=False):
    phase = Phases(timed)
    prepare, fence, dependency = context
    payload = preparation_fixture()
    changed = preparation_fixture()
    changed["faces"][0]["centroid_m"] = encode((2, 0, 0))
    # Fresh generation, repeat, changed conductivity/partition/geometry, and a
    # separately funded-off generation. No old reference charge is reduced.
    calls = [(payload, ["f"], [], 1), (payload, ["f"], [], 1),
             (payload, ["f"], [], 2), (payload, [], ["f"], 2),
             (changed, [], ["f"], 2), (changed, [], ["f"], 2)]
    budget = budget_module.WorkBudget(64 << 20)
    outputs, counts = [], Counter()
    phase.mark("fixture_and_budget_setup")
    for funded in (True, False):
        work = R.OwnedWorkspace(budget, 131072, category="prototype-prepared-generation") if candidate and funded else None
        held = identity = snapshot = None
        if work is not None:
            work.__enter__()
        phase.mark("funded_generation_setup" if funded else "fallback_generation_setup")
        try:
            for data, walls, powers, k in calls:
                C.check(None)
                if candidate:
                    fence(None)
                key = freeze((data, walls, powers, k)) if work is not None else None
                if work is not None:
                    assert len(repr(key)) < 16000
                if work is not None and held is not None and key == identity and freeze(held.value) == snapshot:
                    counts["cache_hits"] += 1
                    outputs.append(freeze(held.value))
                    continue
                replacement = prepare._prepare(data, walls, powers, k, budget=budget, cancelled=None)
                counts["preparations"] += 1
                outputs.append(freeze(replacement.value))
                if work is None:
                    counts["reference_calls"] += 1
                    replacement.close()
                else:
                    previous, held = held, replacement
                    identity, snapshot = key, freeze(held.value)
                    if previous is not None:
                        counts["replacement_retirements"] += 1
                        previous.close()
            phase.mark("funded_generation_calls" if funded else "fallback_generation_calls")
        finally:
            if held is not None:
                held.close()
            held = identity = snapshot = None
            if work is not None:
                work.__exit__(None, None, None)
        phase.mark("funded_generation_retirement" if funded else "fallback_generation_retirement")
    assert budget.reserved_bytes == 0
    return {"values": outputs, "work": dict(counts), "component_calls": len(outputs),
            "peak_reserved_bytes": budget.peak_reserved_bytes, "reserved_after_close": 0,
            "phases_seconds": phase.seconds, "private_dependency": dependency,
            "workload_sha256": digest(freeze(calls))}


def polygon_component():
    moment = module("private_heat_polygon_moment_inventory_r1.py", {"ONE", "MomentPlan", "_Growth", "_plan", "_hex_shape"},
                    {"I": I, "L": L, "START": SimpleNamespace(_size=C.size), "dataclass": dataclass})
    _, text = source("private_heat_functionals_kernel_r1.py")
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "face_second_moment")
    value = ast.get_source_segment(text, node)
    replacements = [
        ("or not dot(normal, normal):", "or not (normal_squared := dot(normal, normal)):"),
        ("        if any(orientation*dot(cross(sub(b, a), sub(p, a)), normal) < 0 for p in shifted):",
         "        edge = sub(b, a)\n        if any(orientation*dot(cross(edge, sub(p, a)), normal) < 0 for p in shifted):"),
        ("/dot(normal, normal) for a in area_vectors]", "/normal_squared for a in area_vectors]"),
        ("    return [[sum(w*(sum(v[i]*v[j] for v in tri)+sum(v[i] for v in tri)*sum(v[j] for v in tri))/12\n"
         "                 for w, tri in zip(weights, fan, strict=True)) for j in range(3)] for i in range(3)]",
         "    result = []\n    for i in range(3):\n        row = []\n        for j in range(3):\n"
         "            value = result[j][i] if j < i else sum(\n"
         "                w*(sum(v[i]*v[j] for v in tri)+sum(v[i] for v in tri)*sum(v[j] for v in tri))/12\n"
         "                for w, tri in zip(weights, fan, strict=True))\n"
         "            row.append(value)\n        result.append(row)\n    return result")]
    for before, after in replacements:
        assert value.count(before) == 1
        value = value.replace(before, after)
    namespace = dict(F.__dict__)
    exec(compile(value, "selected-polygon-normal-edge-symmetry-subset", "exec"), namespace)
    return moment, namespace["face_second_moment"]


def run_polygon(candidate, context, timed=False):
    phase = Phases(timed)
    moment, reused = context
    face = {"vertices_m": [encode(p) for p in ((-2, -1, 0), (2, -1, 0), (2, 1, 0), (-2, 1, 0))],
            "centroid_m": encode((0, 0, 0)), "area_vector_m2": encode((0, 0, 8))}
    metadata = 262144+1024*(100*len(face["vertices_m"])+512)
    budget = budget_module.WorkBudget(64 << 20)
    phase.mark("fixture_and_budget_setup")
    outputs, plans = [], []
    for funded in (True, False):
        with R.OwnedWorkspace(budget, metadata):
            plan = moment._plan(face, metadata, moment._Growth(G, R, None))
        plans.append((plan.total_bytes, plan.retained_bytes, plan.scalar_operations))
        phase.mark("funded_plan" if funded else "fallback_plan")
        optional = R.OwnedWorkspace(budget, 65536, category="prototype-moment-retained-locals") if candidate and funded else None
        if optional is not None:
            optional.__enter__()
        work = R.OwnedWorkspace(budget, plan.total_bytes)
        work.__enter__()
        phase.mark("funded_admission" if funded else "fallback_admission")
        try:
            result = (reused if optional is not None else F.face_second_moment)(face)
            assert len(result) == 3 and len({id(row) for row in result}) == 3
            outputs.append(freeze(result))
            # Retained result layout remains three independent rows/nine slots.
            work.resize_before_allocation_or_after_drop(plan.retained_bytes)
            owner = P.OwnedSolve(result, work)
            result = None
            assert freeze(owner.value) == outputs[-1]
            phase.mark("funded_compute_and_borrow" if funded else "fallback_compute_and_borrow")
            owner.close()
        finally:
            if not work.finished:
                work.__exit__(None, None, None)
            if optional is not None:
                optional.__exit__(None, None, None)
        phase.mark("funded_retirement" if funded else "fallback_retirement")
    assert budget.reserved_bytes == 0
    return {"values": outputs, "component_calls": 2, "work": {"plans": plans,
            "numerical_calls": 2, "candidate_subset_calls": int(candidate), "fallback_calls": 1,
            "triangle_sum_cache": False, "optional_fixed_fixture_bytes": 65536 if candidate else 0},
            "peak_reserved_bytes": budget.peak_reserved_bytes, "reserved_after_close": 0,
            "phases_seconds": phase.seconds, "workload_sha256": digest(face)}


def run_screen(candidate, timed=False):
    phase = Phases(timed)
    points = [(('cell', i), tuple(map(G.mpq, (i % 5-2, i//5-2, (i*i) % 3)))) for i in range(25)]
    points += [(('wall', 'overflow'), (G.mpq(2**2048), G.mpq(0), G.mpq(0))),
               (('power', 'subnormal'), (G.mpq(1, 2**1075), G.mpq(-1, 2**1075), G.mpq(0)))]
    centres = ((0, 0, 0), (2, -1, 0), (-1, 2, 1))
    budget = budget_module.WorkBudget(8 << 20)
    owner = EnclosureOwner(points, budget) if candidate else None
    phase.mark("generation_setup")
    outputs = []
    try:
        for centre in centres:
            poll = Poll()
            screen = CachedScreen(points, centre, 6, poll, owner) if candidate else F.ScreenedSupport(points, centre, 6, poll)
            ranking = screen.full_ranking()
            outputs.append(freeze((screen.shell, ranking, screen.diagnostics, poll.calls)))
        phase.mark("three_faces_and_fresh_rankings")
        changed = list(points)
        changed[0] = (changed[0][0], (G.mpq(99), *changed[0][1][1:]))
        poll = Poll()
        screen = CachedScreen(changed, centres[0], 6, poll, owner) if candidate else F.ScreenedSupport(changed, centres[0], 6, poll)
        outputs.append(freeze((screen.shell, screen.full_ranking(), screen.diagnostics, poll.calls)))
        phase.mark("stale_generation_reference_fallback")
        work = {"faces": 4, "fresh_rankings": 4, "centre_enclosures": 12,
                "observation_enclosures": 3*len(points)*(2 if candidate else 4),
                "table_misses": owner.misses if owner else 0, "table_hits": owner.hits if owner else 0,
                "stale_fallback_faces": 1}
    finally:
        screen = None
        if owner is not None:
            owner.close()
    phase.mark("generation_retirement")
    assert budget.reserved_bytes == 0
    return {"values": outputs, "component_calls": 4, "work": work,
            "peak_reserved_bytes": budget.peak_reserved_bytes, "reserved_after_close": 0,
            "phases_seconds": phase.seconds, "workload_sha256": digest(freeze((points, centres, changed)))}


def run_component(name, candidate, context, timed=False):
    if name == "C2":
        return run_preparation(candidate, context, timed)
    if name == "C13":
        return run_polygon(candidate, context, timed)
    if name == "C14":
        return run_screen(candidate, timed)
    rows = [run_basis(name, index, candidate) for index in range(4)]
    # Include explicit unfunded fallback cost in each measured generation.
    rows.append(run_basis(name, 0, candidate, force_fallback=True))
    for row in rows:
        assert row["outcome"] == "success"
        row.pop("trace_rows", None)
    return {"values": [row["values"] for row in rows], "component_calls": 5,
            "work": [{key: row[key] for key in ("executed", "reused", "logical_operations", "polls", "cache_enabled")} for row in rows],
            "peak_reserved_bytes": max(row["peak_reserved_bytes"] for row in rows), "reserved_after_close": 0,
            "phases_seconds": {}, "workload_sha256": digest(freeze((name, POINTS, FLUX_NORMAL, FLUX_MOMENT, FLUX_K)
                                                                       if name == "C12" else (name, POINTS))),
            "setup_cost_scope": "Per-call budget/arena/cache construction, original guards, instrumentation and retirement included in total"}


def sample_components(selected, contexts, samples, timed):
    rows, expected, preflight = [], {}, {}
    # Canonical comparisons and all result hashing are outside measured windows.
    for name in selected:
        baseline = run_component(name, False, contexts.get(name))
        candidate = run_component(name, True, contexts.get(name))
        assert baseline["values"] == candidate["values"], name
        expected[name] = digest(baseline["values"])
        preflight[name] = {"baseline_digest": expected[name], "candidate_digest": digest(candidate["values"]),
                           "baseline_work": baseline["work"], "candidate_work": candidate["work"],
                           "workload_sha256": baseline["workload_sha256"]}
    for sample in range(samples):
        arms = (False, True, True, False) if sample % 2 == 0 else (True, False, False, True)
        for name in selected:
            for position, candidate in enumerate(arms):
                began = perf_counter() if timed else None
                output = run_component(name, candidate, contexts.get(name), timed)
                seconds = perf_counter()-began if timed else None
                signature = digest(output.pop("values"))
                assert signature == expected[name], (name, sample, position, "sample digest mismatch")
                row = {"candidate": name, "block": sample, "position": position,
                       "order": "ABBA" if sample % 2 == 0 else "BAAB",
                       "arm": "candidate" if candidate else "baseline", "result_digest": signature,
                       "matches_outside_timing_preflight": True, **output}
                if timed:
                    row["seconds"] = seconds
                else:
                    row.pop("phases_seconds")
                rows.append(row)
    return preflight, rows


def changed_component_checks(contexts):
    """Bounded new Fraction-subset refusal checks, outside all sample clocks."""
    if "C13" not in contexts:
        return {}
    candidate = contexts["C13"][1]
    face = {"vertices_m": [encode(p) for p in ((-2, -1, 0), (2, -1, 0), (2, 1, 0), (-2, 1, 0))],
            "centroid_m": encode((0, 0, 0)), "area_vector_m2": encode((0, 0, 8))}
    cases = []
    for name in ("missing_vertices", "duplicate", "zero_normal", "wrong_area", "wrong_centroid", "nonplanar"):
        item = json.loads(json.dumps(face))
        if name == "missing_vertices":
            item.pop("vertices_m")
        elif name == "duplicate":
            item["vertices_m"].append(item["vertices_m"][0])
        elif name in ("zero_normal", "wrong_area"):
            item["area_vector_m2"] = encode((0, 0, 0 if name == "zero_normal" else 1))
        elif name == "wrong_centroid":
            item["centroid_m"] = encode((1, 0, 0))
        else:
            item["vertices_m"][0] = encode((-2, -1, 1))
        outcomes = []
        for helper in (F.face_second_moment, candidate):
            try:
                helper(item)
            except (ValueError, TypeError, KeyError, ZeroDivisionError) as error:
                outcomes.append((type(error).__name__, str(error)))
            else:
                raise AssertionError("Expected polygon refusal: " + name)
        assert outcomes[0] == outcomes[1], name
        cases.append({"case": name, "equal_refusal": outcomes[0]})
    return {"C13": {"normal_edge_symmetry_subset_fraction_refusals": cases,
                    "triangle_sum_cache_exercised": False}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--private-helpers", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--correctness", action="store_true")
    mode.add_argument("--benchmark", action="store_true")
    mode.add_argument("--smoke", action="store_true", help="Exact sample loop with no harness clock reads or timing fields")
    parser.add_argument("--candidate", action="append", choices=("C1", "C2", "C12", "C13", "C14"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--queue-go", action="store_true", help="Only after explicit queue GO; this flag is not authority")
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be a new path")
    if args.benchmark and not args.queue_go:
        parser.error("Benchmark requires actual queue GO and --queue-go")
    if not 1 <= args.samples <= 3:
        parser.error("One to three samples only")
    process = psutil.Process()
    allowed = process.cpu_affinity()
    process.cpu_affinity([allowed[0]])
    began = None if args.smoke else perf_counter()
    selected = args.candidate or ["C1", "C2", "C12", "C13", "C14"]
    if (args.benchmark or args.smoke) and "C2" in selected and args.private_helpers is None:
        parser.error("C2 component sampling requires --private-helpers; public source fence remains refused")
    results = {}
    for name in selected:
        try:
            results[name] = (basis_tests(name) if name in ("C1", "C12") else
                             prepared_tests() if name == "C2" else polygon_tests() if name == "C13" else enclosure_tests())
        except Exception as error:
            message = str(error).replace(str(ROOT), "<CHECKOUT>")
            if args.private_helpers is not None:
                message = message.replace(str(args.private_helpers), "<PRIVATE_HELPERS>")
            results[name] = {"status": "FAIL", "error": type(error).__name__, "message": message,
                             "limits": ["Unexpected failure; this candidate did not pass"]}
    record = {"schema": "plan40b.functional-tests.r2", "mode": "benchmark" if args.benchmark else "smoke" if args.smoke else "correctness",
              "source_map_sha256": MAP_SHA, "sources": bindings,
              "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "runtime": {"python": sys.version, "gmpy2": G.version(), "gmp": G.mp_version(),
                          "single_cpu": process.cpu_affinity()},
              "workload_sha256": digest([[canonical(v) for v in point]+[canonical(v) for v in origin]+[canonical(scale)]
                                         for point, origin, scale in POINTS]),
              "results": results,
              "process_memory_snapshot": process.memory_info()._asdict(),
              "status": "PASS", "qualification": "Bounded tested components only; explicit runtime/deployment gaps remain",
              "benchmark_samples": [],
              "candidates": {name: {"status": ("FAIL" if result["status"] == "FAIL" else
                                               "BLOCKED" if result["status"].startswith("PARTIAL_ENTRY") else "PASS"),
                             "checks": result["status"], "evidence": "results."+name,
                             "limitations": result.get("limits", [result.get("gap", "")])}
                             for name, result in results.items()}}
    if not args.smoke:
        record["correctness_setup_seconds_not_comparison"] = perf_counter()-began
    if args.benchmark or args.smoke:
        if any(item["status"] != "PASS" for item in record["candidates"].values()):
            record["status"] = "FAIL_PREFLIGHT_NO_SAMPLES"
        else:
            try:
                setup_began = perf_counter() if args.benchmark else None
                contexts = {}
                if "C2" in selected:
                    contexts["C2"] = preparation_component()
                if "C13" in selected:
                    contexts["C13"] = polygon_component()
                record["changed_component_checks"] = changed_component_checks(contexts)
                if args.benchmark:
                    record["benchmark_component_setup_seconds"] = perf_counter()-setup_began
                checks, samples = sample_components(selected, contexts, args.samples, args.benchmark)
                record["sample_preflight"] = checks
                record["benchmark_samples" if args.benchmark else "smoke_samples"] = samples
                record["sampling"] = {"blocks": args.samples, "per_arm_samples": 2*args.samples,
                                      "order": "alternating ABBA/BAAB", "hashing_and_equality_outside_timing": True,
                                      "scope": "Bounded source-extracted components; no production/worker qualification",
                                      "setup_and_fallback_costs": "Included in every full arm; phase timings for C2/C13/C14 only in benchmark mode"}
            except Exception as error:
                record["status"] = "FAIL_SAMPLE_LOOP"
                message = str(error).replace(str(ROOT), "<CHECKOUT>")
                if args.private_helpers is not None:
                    message = message.replace(str(args.private_helpers), "<PRIVATE_HELPERS>")
                record["sample_failure"] = {"type": type(error).__name__, "message": message}
                for name in selected:
                    record["candidates"][name]["status"] = "FAIL"
                    record["candidates"][name]["sample_loop_failed"] = True
    if any(result["status"] == "FAIL" for result in results.values()):
        record["status"] = "FAIL"
    elif any(item["status"] == "BLOCKED" for item in record["candidates"].values()):
        record["status"] = "BLOCKED"
    record["process_memory_snapshot"] = process.memory_info()._asdict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
    print(json.dumps({"status": record["status"], "output": str(args.output),
                      "candidates": {key: value["status"] for key, value in record["candidates"].items()}}))
    if record["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
