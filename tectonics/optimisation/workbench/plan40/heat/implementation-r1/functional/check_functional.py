"""Bounded imported C13 successor/native-owner checks, never a timing entry."""
if not __debug__:
    raise RuntimeError("Implementation checks require assertions")

import argparse
from contextlib import ExitStack
from fractions import Fraction
import gc
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--testing", type=Path, required=True, help="Frozen functional testing directory")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    parser.error("Output must be new")
HERE = Path(__file__).resolve().parent
old_harness = args.testing / "functional_tests.py"
if sha256(old_harness.read_bytes()).hexdigest() != "a9ea95b4f2971ed606716a019d4c7bec5a98dc7f9ad4075fca4a99e09596b013":
    raise ValueError("Frozen source loader changed")
# Loading the old entry establishes its pinned selected dependency modules; it
# does not call main, its correctness suite, sample loop or any clock.
ns = runpy.run_path(str(old_harness), run_name="functional_selected_component_dependencies")
module, source = ns["module"], ns["source"]
G, R, C, F, L = (ns[name] for name in ("G", "R", "C", "F", "L"))
Budget, Poll, freeze, encode, digest = ns["budget_module"].WorkBudget, ns["Poll"], ns["freeze"], ns["encode"], ns["digest"]
module("_validation.py", alias="atlas_tectonics._validation")
backend = module("exact_arithmetic.py", alias="atlas_tectonics.exact_arithmetic")
assert backend.library() is G
COUNT = module("private_heat_counted_blocks_r2.py")
RETAIN = module("private_heat_owned_value_r4.py")
START = module("private_heat_geometry_inventory_r1.py", {"_size"}, {"sys": sys})
fence_calls = 0
def component_fence(cancel):
    global fence_calls
    C.check(cancel)
    for name in ("private_heat_geometry_inventory_r1.py", "private_heat_polygon_moment_inventory_r1.py",
                 "private_heat_functionals_kernel_r1.py", "private_heat_owned_value_r4.py",
                 "private_heat_counted_blocks_r2.py", "private_heat_gmp_resources_r1.py"):
        source(name)
    fence_calls += 1
START._verify_sources = component_fence
M = module("private_heat_polygon_moment_inventory_r1.py")
BASE = module("private_heat_polygon_moment_inventory_r4.py")

def imported(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value

NUM = imported("private_heat_polygon_numerics_40b_r1")
NEW = imported("private_heat_polygon_moment_40b_r1")
assert NEW.M is M and NEW.RETAIN is RETAIN and NEW.NUMERICS is NUM
# These two downstream consumers are not executed. Their explicit shells allow
# the complete functional module to import for binding verification only.
for name in ("private_heat_functional_bounds_kernel_r2", "private_heat_functionals_parallel_r1"):
    sys.modules[name] = ModuleType(name)
F.K = SimpleNamespace(PRECISIONS=(64, 128))
FUNCTIONAL = imported("private_heat_functionals_kernel_40b_r1")
assert FUNCTIONAL.MOMENT is NEW
_, predecessor_functional = source("private_heat_functionals_kernel_r5.py")
assert Path(FUNCTIONAL.__file__).read_text() == predecessor_functional.replace(
    "import private_heat_polygon_moment_inventory_r4 as MOMENT", "import private_heat_polygon_moment_40b_r1 as MOMENT")

def shape(points, centre, normal):
    return {"vertices_m": [encode(p) for p in points], "centroid_m": encode(centre), "area_vector_m2": encode(normal)}

triangle = shape(((0, 0, 0), (3, 0, 0), (0, 3, 0)), (1, 1, 0), (0, 0, Fraction(9, 2)))
rectangle = shape(((-2, -1, 0), (2, -1, 0), (2, 1, 0), (-2, 1, 0)), (0, 0, 0), (0, 0, 8))
reverse = json.loads(json.dumps(rectangle))
reverse["vertices_m"].reverse()
offset, small = Fraction(2**150, 7), Fraction(1, 2**80)
tilted = shape(((offset, 0, 0), (offset+3*small, 0, 3*small), (offset, 3*small, 3*small)),
               (offset+small, small, 2*small), (-9*small*small/2, -9*small*small/2, 9*small*small/2))
cases = {"triangle": triangle, "rectangle": rectangle, "reverse": reverse, "far_tiny_tilted": tilted}

def invoke(function, face, limit=64 << 20, cancel_at=None):
    budget, poll = Budget(limit), Poll(cancel_at)
    try:
        owner = function(face, budget=budget, cancel=poll)
    except Exception as error:
        output = {"outcome": type(error).__name__, "message": str(error),
                  "charged_while_error_alive": budget.reserved_bytes, "polls": poll.calls}
        error.__traceback__ = None
    else:
        value = owner.value
        matrix = value["moment"]
        plan = value["inventory"]
        assert len(matrix) == 3 and len({id(row) for row in matrix}) == 3
        output = {"outcome": "success", "value": freeze(matrix), "digest": digest(freeze(matrix)),
                  "plan": freeze(plan.__dict__), "plan_bytes": plan.total_bytes,
                  "retained_bytes": budget.reserved_bytes, "polls": poll.calls}
        value = matrix = plan = None
        owner.close()
        try:
            owner.value
        except RuntimeError:
            output["closed_borrow_refused"] = True
        else:
            raise AssertionError("Closed owner remained borrowable")
    gc.collect()
    output["peak_bytes"] = budget.peak_reserved_bytes
    output["after_drop_bytes"] = budget.reserved_bytes
    assert budget.reserved_bytes == 0, output
    return output

rows = []
for name, face in cases.items():
    baseline = invoke(BASE.second_moment, face)
    candidate = invoke(NEW.second_moment, face)
    assert baseline["outcome"] == candidate["outcome"] == "success", (name, baseline, candidate)
    for key in ("value", "digest", "plan", "plan_bytes", "polls", "peak_bytes"):
        assert baseline[key] == candidate[key], (name, key)
    rows.append({"case": name, "baseline": baseline, "candidate": candidate})

faults = []
for name in ("missing", "duplicate", "zero_normal", "wrong_area", "wrong_centroid", "nonplanar"):
    face = json.loads(json.dumps(rectangle))
    if name == "missing": face.pop("vertices_m")
    elif name == "duplicate": face["vertices_m"].append(face["vertices_m"][0])
    elif name == "zero_normal": face["area_vector_m2"] = encode((0, 0, 0))
    elif name == "wrong_area": face["area_vector_m2"] = encode((0, 0, 1))
    elif name == "wrong_centroid": face["centroid_m"] = encode((1, 0, 0))
    else: face["vertices_m"][0] = encode((-2, -1, 1))
    a, b = invoke(BASE.second_moment, face), invoke(NEW.second_moment, face)
    assert (a["outcome"], a["message"], a["polls"]) == (b["outcome"], b["message"], b["polls"]), name
    faults.append({"case": name, "baseline": a, "candidate": b})
for at in (1, 7, rows[1]["baseline"]["polls"]-1):
    a = invoke(BASE.second_moment, rectangle, cancel_at=at)
    b = invoke(NEW.second_moment, rectangle, cancel_at=at)
    assert a["outcome"] == b["outcome"] == "CancelledError"
    assert a["polls"] == b["polls"]
    faults.append({"cancel_at": at, "baseline": a, "candidate": b})
limit = rows[1]["baseline"]["plan_bytes"]-1
a, b = invoke(BASE.second_moment, rectangle, limit), invoke(NEW.second_moment, rectangle, limit)
assert a["outcome"] == b["outcome"] == "MemoryLimitError"
faults.append({"one_byte_short_plan": limit, "baseline": a, "candidate": b})

original = NUM.face_second_moment
NUM.face_second_moment = lambda face: original(face)
try:
    rejected = invoke(NEW.second_moment, rectangle)
    assert rejected["outcome"] == "ValueError" and "callable binding changed" in rejected["message"]
finally:
    NUM.face_second_moment = original
faults.append({"replaced_callable": rejected})
with tempfile.TemporaryDirectory(prefix="source-drift-", dir=HERE) as temp:
    changed = Path(temp) / "numerics.py"
    changed.write_bytes(Path(NUM.__file__).read_bytes()+b"\n# changed\n")
    original_path, NUM.__file__ = NUM.__file__, str(changed)
    try:
        rejected = invoke(NEW.second_moment, rectangle)
        assert rejected["outcome"] == "ValueError" and "source changed" in rejected["message"]
    finally:
        NUM.__file__ = original_path
faults.append({"changed_source": rejected})

# Fail at the real retained-transfer boundary, after prospective computation.
old_transfer = RETAIN.transfer
def fail_transfer(*_args, **_kwargs):
    raise RuntimeError("Injected retained transfer failure")
RETAIN.transfer = fail_transfer
try:
    a, b = invoke(BASE.second_moment, rectangle), invoke(NEW.second_moment, rectangle)
    assert a["outcome"] == b["outcome"] == "RuntimeError"
    assert a["charged_while_error_alive"] > 0 and b["charged_while_error_alive"] > 0
finally:
    RETAIN.transfer = old_transfer
faults.append({"retained_transfer_failure": {"baseline": a, "candidate": b}})

# A real selected _face consumer calls the wired moment provider and owns the
# prescribed-power row. Full non-power reconstruction is explicitly outside this check.
budget = Budget(64 << 20)
with ExitStack() as stack:
    def moment(fid):
        assert fid == "f"
        return stack.enter_context(FUNCTIONAL.MOMENT.second_moment(rectangle, budget=budget)).value["moment"]
    owner = FUNCTIONAL._face("f", {"centre": (0, 0, 0), "normal": (0, 0, 8), "owners": [(0, 1)]},
        {"points": {}, "geometry": {}, "neumann": {"f"}}, moment,
        budget=budget, cancelled=None, certification_precisions=(64, 128))
    assert owner.value["diagnostics"]["prescribed_power_exact"]
    owner.close()
assert budget.reserved_bytes == 0

report = {"schema": "plan40b.functional-implementation.r1", "status": "PASS", "candidate": "C13",
          "sources": ns["bindings"], "implementation": {path.name: sha256(path.read_bytes()).hexdigest()
              for path in HERE.glob("private_heat_*40b_r1.py")},
          "check_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
          "cases": rows, "faults": faults, "component_fence_calls": fence_calls,
          "actual_native_retained_owner": True, "actual_backend_library": G.version(),
          "functional_import_and_prescribed_power_consumer": "PASS",
          "limits": ["Full successor modules imported; baseline M1/M4 and native counted-retention/WorkBudget executed",
                     "Geometry startup source fence explicitly dependency-injected with selected component hashes; whole original runtime fence not qualified",
                     "Functional downstream bounds/parallel modules are import-only shells; no non-power face, worker, forward/issuer/checkpoint qualification",
                     "No timing; modest measured prototype result cannot be inherited as successor runtime saving"]}
with args.output.open("x", encoding="utf-8") as stream:
    json.dump(report, stream, sort_keys=True, indent=2)
print(json.dumps({"status": "PASS", "cases": len(rows), "faults": len(faults), "candidate": "C13"}))
