"""Source-bound exact polygon control, not production code or a timing test."""
if not __debug__:
    raise RuntimeError("Controls require assertions; optimised Python is refused")

import ast
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
MAP_SHA = "1d1e2c79fe7825e276e2a33f2d5c18fe3157da8ef4b41ab0c3c347bca9295fcf"
raw_map = (ROOT / "tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json").read_bytes()
if hashlib.sha256(raw_map).hexdigest() != MAP_SHA:
    raise ValueError("Different selected source generation")
selection = json.loads(raw_map)
entries = {Path(entry["member"]).name: entry for entry in selection["entries"]}
sources = {}


def source(name):
    entry = entries[name]
    raw = (ROOT / entry["public_path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["public_sha256"]:
        raise ValueError("Selected member source mismatch")
    sources[entry["public_path"]] = entry["public_sha256"]
    return raw.decode("utf-8")


text = source("private_heat_functionals_kernel_r1.py")
for name in ("private_heat_polygon_moment_inventory_r1.py",
             "private_heat_polygon_moment_inventory_r4.py",
             "private_heat_support_basis_resources_r1.py",
             "private_heat_support_basis_resources_r2.py",
             "private_heat_functionals_kernel_r5.py",
             "private_heat_functionals_parallel_r1.py",
             "private_heat_exact_growth_r1.py"):
    source(name)
tree = ast.parse(text)
names = {"decode", "vector", "dot", "sub", "cross", "face_second_moment"}
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {node.name for node in nodes} == names


class Exact:
    """Count executed scalar operations, with Fraction canonical values."""
    counts = Counter()

    def __init__(self, numerator=0, denominator=None):
        self.value = (Fraction(numerator) if denominator is None
                      else Fraction(numerator, denominator))

    @staticmethod
    def unwrap(value):
        return value.value if isinstance(value, Exact) else value

    def operation(self, other, name, function, reverse=False):
        self.counts[name] += 1
        a, b = self.value, self.unwrap(other)
        return Exact(function(b, a) if reverse else function(a, b))

    def __add__(self, other):
        return self.operation(other, "add", lambda a, b: a+b)

    __radd__ = __add__

    def __sub__(self, other):
        return self.operation(other, "subtract", lambda a, b: a-b)

    def __mul__(self, other):
        return self.operation(other, "multiply", lambda a, b: a*b)

    __rmul__ = __mul__

    def __truediv__(self, other):
        return self.operation(other, "divide", lambda a, b: a/b)

    def __neg__(self):
        self.counts["negate"] += 1
        return Exact(-self.value)

    def __eq__(self, other):
        return self.value == self.unwrap(other)

    def __lt__(self, other):
        return self.value < self.unwrap(other)

    def __hash__(self):
        return hash(self.value)

    def __bool__(self):
        return bool(self.value)


base = {"Q": Exact}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "selected-polygon", "exec"), base)
node = next(node for node in nodes if node.name == "face_second_moment")
candidate_text = ast.get_source_segment(text, node)


def replace_once(old, new):
    global candidate_text
    assert candidate_text.count(old) == 1, old
    candidate_text = candidate_text.replace(old, new)


replace_once("or not dot(normal, normal):", "or not (normal_squared := dot(normal, normal)):")
replace_once("        if any(orientation*dot(cross(sub(b, a), sub(p, a)), normal) < 0 for p in shifted):",
             "        edge = sub(b, a)\n        if any(orientation*dot(cross(edge, sub(p, a)), normal) < 0 for p in shifted):")
replace_once("/dot(normal, normal) for a in area_vectors]", "/normal_squared for a in area_vectors]")
replace_once("    first = [sum(w*sum(v[j] for v in triangle)/3 for w, triangle in zip(weights, fan, strict=True))\n             for j in range(3)]",
             "    triangle_sums = [[None]*3 for _ in fan]\n"
             "    def remember(t, j, value):\n"
             "        triangle_sums[t][j] = value\n"
             "        return value\n"
             "    first = [sum(w*remember(t, j, sum(v[j] for v in triangle))/3\n"
             "                 for t, (w, triangle) in enumerate(zip(weights, fan, strict=True)))\n"
             "             for j in range(3)]")
replace_once("    return [[sum(w*(sum(v[i]*v[j] for v in tri)+sum(v[i] for v in tri)*sum(v[j] for v in tri))/12\n                 for w, tri in zip(weights, fan, strict=True)) for j in range(3)] for i in range(3)]",
             "    result = []\n"
             "    for i in range(3):\n"
             "        row = []\n"
             "        for j in range(3):\n"
             "            value = result[j][i] if j < i else sum(\n"
             "                w*(sum(v[i]*v[j] for v in tri)+triangle_sums[t][i]*triangle_sums[t][j])/12\n"
             "                for t, (w, tri) in enumerate(zip(weights, fan, strict=True)))\n"
             "            row.append(value)\n"
             "        result.append(row)\n"
             "    return result")
candidate = dict(base)
exec(compile(candidate_text, "polygon-reuse-prototype", "exec"), candidate)


def encoded(vector):
    return [[format(Fraction(v).numerator, "x"), format(Fraction(v).denominator, "x")]
            for v in vector]


def shape(points, centre, normal):
    return dict(vertices_m=[encoded(p) for p in points], centroid_m=encoded(centre),
                area_vector_m2=encoded(normal))


def run(function, face):
    Exact.counts = Counter()
    try:
        result = function(face)
        assert len(result) == 3 and all(len(row) == 3 for row in result)
        assert len({id(row) for row in result}) == 3
        value = [[(q.value.numerator, q.value.denominator) for q in row] for row in result]
        outcome = {"value": value}
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as error:
        outcome = {"error": type(error).__name__, "message": str(error)}
    return outcome, dict(Exact.counts)


triangle = shape([(0, 0, 0), (3, 0, 0), (0, 3, 0)], (1, 1, 0), (0, 0, Fraction(9, 2)))
rectangle = shape([(-2, -1, 0), (2, -1, 0), (2, 1, 0), (-2, 1, 0)], (0, 0, 0), (0, 0, 8))
reverse = deepcopy(rectangle)
reverse["vertices_m"].reverse()
offset, small = Fraction(2**150, 7), Fraction(1, 2**80)
tilted = shape([(offset, 0, 0), (offset+3*small, 0, 3*small), (offset, 3*small, 3*small)],
               (offset+small, small, 2*small),
               (-9*small*small/2, -9*small*small/2, 9*small*small/2))
cases = {"triangle": triangle, "rectangle": rectangle, "reverse_orientation": reverse,
         "tiny_tilted_far_origin": tilted}
for name, change in (
    ("missing_vertices", lambda f: f.pop("vertices_m")),
    ("duplicate_vertex", lambda f: f["vertices_m"].append(f["vertices_m"][0])),
    ("too_few_vertices", lambda f: f["vertices_m"].pop()),
    ("wrong_area", lambda f: f.update(area_vector_m2=encoded((0, 0, 1)))),
    ("wrong_centroid", lambda f: f.update(centroid_m=encoded((2, 1, 0)))),
    ("not_planar", lambda f: f["vertices_m"].__setitem__(0, encoded((0, 0, 1)))),
):
    bad = deepcopy(triangle)
    change(bad)
    cases[name] = bad
cases["concave_ring"] = shape([(0, 0, 0), (4, 0, 0), (1, 1, 0), (0, 4, 0)], (1, 1, 0), (0, 0, 4))
results = {}
for name, face in cases.items():
    original, original_counts = run(base["face_second_moment"], face)
    reused, reused_counts = run(candidate["face_second_moment"], face)
    assert original == reused, name
    row = {"outcome": "refused" if "error" in original else "accepted",
           "same_canonical_values_or_refusal": True,
           "baseline_operations": original_counts, "candidate_operations": reused_counts}
    if "error" not in original:
        n = len(face["vertices_m"])
        t = n-2
        expected = {"multiply": 18*t, "divide": 3*t, "add": 72*t, "subtract": 3*n*(n-1)}
        actual = {k: original_counts.get(k, 0)-reused_counts.get(k, 0) for k in expected}
        assert actual == expected, (name, actual, expected)
        row["eliminated_operations"] = actual
    else:
        row["refusal"] = original
    results[name] = row

print(json.dumps({"status": "PASS", "source_map_sha256": MAP_SHA,
                  "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "sources": sources, "cases": results,
                  "scope": "Exact Fraction logical prototype; no Atlas imports, timing, GMP, WorkBudget, workers or production changes",
                  "limits": ["Existing full polygon inventory and cancellation boundaries must remain in production",
                             "Temporary triangle-sum references/containers require a complete storage accounting argument",
                             "Source/runtime and consumer identities require successor binding"]}, indent=2))
