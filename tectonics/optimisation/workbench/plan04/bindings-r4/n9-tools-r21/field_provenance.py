"""Source-derived N9 pose-producer provenance, joined through reader-proved records.

Inputs cross the existing independent source/reader proof boundary. No files
named by a receipt are loaded; no producer/runtime is imported. r4 binds the two
N9 pose producers, W._pose_vector (b-ray) and E._representative_pose (b-quat), at
every call site in the selected package inventory, found by a static AST scan of
all its modules rather than only W and E. Reviewed call sites (full6, p1820c-r4):

- W internal: _wall_leaf, _pose_planes, _measure_walls (rigid and coarse wall routes).
- E internal: build_exterior_mesh, _build_exterior_mesh_record (rigid exterior mesh).
- D = integration_differential_geometry (nine-kind differential route): _ray_box,
  _pose_binding, _source_planes, _boundary_leaf and _constraint_pose (2) call
  W._pose_vector; posed_boundary calls E._representative_pose.
- P = integration_current_force_pose: current_force_pose calls E._representative_pose.

Any other call site is an unreviewed access (REVIEW), and so is each of:
- a producer referenced without a direct call, or named on an unresolved receiver;
- a producer imported from a non-producer module, or bound at module/class scope or
  through a global declaration outside its own module, or a producer module bound at
  class scope (a re-export no scan follows);
- any string, docstrings included, naming a producer or a producer module (getattr,
  attrgetter, import_module, __import__, sys.modules keys, __doc__ reads);
- a producer module used other than as an attribute base (rebound, passed, returned),
  star-imported, read through a non-inert dunder (__name__ and __file__ included),
  getattr/hasattr with a non-literal or producer name, or vars/globals/locals where a
  producer is bound;
- a producer module read through another selected module's binding, a producer module's
  own bindings included (X.W, E.W, from .X import W, from .X import *, a simple
  assignment of either, getattr(X, name), X.__dict__, a module read by fixed name
  through import_module, __import__ or sys.modules, directly or through a name bound to
  one of them, relative names included) and then used as a value, read by a computed
  name, or read for the producer or a member of its closure; its other members are read
  as directly. Aliases are followed in their own and nested scopes (module-wide when
  global, from the owning function when nonlocal), three deep and for eight origins per
  statement; a class-attribute alias, or one past either limit, counts as reading any
  member;
- source text run in place (exec, eval or compile of a string, bytes or f-string, or of a
  name or attribute that an assignment anywhere in the module binds to one);
- a write to any selected package module or to an object imported from one (attribute
  or item assignment or deletion, setattr, delattr, operator.setitem/delitem, the
  __setattr__/__delattr__/__setitem__/__delitem__ methods, dict methods on vars(x) or
  x.__dict__, also through a simple alias or a class attribute holding one), or a
  replacement of a selected module in sys.modules by fixed name, wherever it is made;
- an import from a test/fixture path.
Two selected files that import as one module (x.py and x/__init__.py), or an inventoried
extension module or non-source package __init__ claiming a scanned module's name, fail
input integrity; the installed startup's finder separately refuses any non-.py origin.
Records or sources too deep to decode or parse fail input integrity too.
Computed names (string arithmetic, exec/eval of computed text, computed import names,
target strings such as mock.patch's, globals()/locals() item reads), relays through
containers, unpacking or call arguments, and other mutation through method calls remain
outside any static scan. Scope: the package inventory (source_hashes, canonical
relative keys) minus test/fixture paths below the package directory; profile-bound
helpers are outside it.

Consequence routes: other modules that call a producer-module function reaching
the producer (W._endpoint_volume from the E builders and spatial ALE,
W.enclose_rotating_wall from spatial ALE) carry pose consequences past the joined
records. Under the rounding pair they make the slots they reach REVIEW.

A proved relation (identity or the reviewed rounding pair) also needs the
producer's package import closure byte-identical across arms, apart from the
reviewed W/E width transforms; otherwise REVIEW.

Persisted joins, where the selected route stores the producer's outputs:
- E (rigid exterior mesh): representative_quaternion and pose_operator_error_bound
  (= 4*e) come from one _representative_pose(segments, goal) call, stored with those
  segments and their W trajectory identity (chronological history). Both arms must
  share every invocation input (segments, endpoint, width, funding, source), which
  fix the goal. Differential meshes carry no pose fields.
- W (coarse route only): _pose_vector outputs are intermediates. Their persisted
  consequences are the wall-measure record's certified enclosures: rows' flux bounds
  and allocations (_wall_leaf) and exterior cells' endpoint/geometry volume bounds
  (_pose_planes); _measure_walls' inverse vertices drive coverage subdivision and
  refusal only. Each arm's record must satisfy the producer's own reader rules and
  exact assembly relations; both arms' enclosures of one face, cell, interval and
  history must intersect, and pose-independent faces must be equal.
- D and P: consequences are differential geometry enclosures and force checks with
  no propagated cross-arm bound. DESIGN section 3: tests on posed values flip only
  toward refusal, which the stage outcomes judge.

Per-slot verdicts: FAIL (a demonstrated contradiction), REVIEW (unbound, or changed
without a bound), BOUND (the producer and caller relation is identity, or every
persisted output is joined; numerical rows still judge the values). NOT_APPLICABLE
when no selected module calls a producer. No numerical allowance is granted here.
"""
from __future__ import annotations
import ast
from collections.abc import Mapping
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re

SCHEMA = "atlas.private.plan04-field-provenance.r5"
RECEIPT_SCHEMA = "atlas.private.plan04-producer-receipt.r5"
SHA = re.compile("[0-9a-f]{64}\\Z")
HEX = re.compile(r"-?0x[0-9a-fA-F]+\Z")
MAX_BITS = 8_388_608
# family -> (module stem, producer function)
PRODUCERS = {"W": ("integration_wall_measures", "_pose_vector"),
             "E": ("integration_exterior_mesh", "_representative_pose")}
PRODUCER_NAMES = {name: family for family, (_, name) in PRODUCERS.items()}
STEMS = {stem: family for family, (stem, _) in PRODUCERS.items()}
MODULES = {stem + ".py": family for family, (stem, _) in PRODUCERS.items()}
W_SOURCE = "d6b7d472246af0e8a9415b01465f035c0c860c7b358126fd1bba5c0025e671e0"
W_ROUNDED = "a7a7dc432a45439aa47d912fd6d1424be7f7c1081d03bd079aa075be6550ebef"
E_SOURCE = "d338238e1abe11db8e01a4b4ee91f99443727fb082f9d9cb6799344e82d445f4"
E_ROUNDED = "4b5b11c46d5602ab20ad46a2401ef3c34f64e281d86cdf9c1efd127e3f22840d"
KNOWN = {"W": {W_SOURCE, W_ROUNDED}, "E": {E_SOURCE, E_ROUNDED}}
ROUNDED_PAIRS = {"W": (W_SOURCE, W_ROUNDED), "E": (E_SOURCE, E_ROUNDED)}
M_SOURCE = "ab0f31f8231a792df45c0016c090496180abe4847ab0194491f6910125dd8138"
M_ROUNDED = "bfe89a0e5f9cfcc3135f2f6910c5f22526d2eb462f88bc034dbdcc9c1eea241e"
WM, EM = "integration_wall_measures.py", "integration_exterior_mesh.py"
DG, CFP = "integration_differential_geometry.py", "integration_current_force_pose.py"
DM = "integration_differential_mesh.py"
# The reviewed N9 width transforms a proved relation tolerates inside a producer's import closure,
# matched by canonical key and exact pins. On r4 the W and E closures are one module set. E inside
# W's: W's producer reads only W-internal bindings, integration_volume, integration_volume_overlap
# and fractions. W inside E's: E's producer reads W._decode, which the W transform leaves unchanged,
# and on the width arm the new W rounding helpers, which the E proof executed from these pinned
# files. The differential-mesh transform (DM, M_SOURCE -> M_ROUNDED) lies outside both closures on
# r4 and is not tolerated inside one: no such argument covers it.
TRANSFORMS = frozenset({("atlas_tectonics/" + WM, W_SOURCE, W_ROUNDED), ("atlas_tectonics/" + EM, E_SOURCE, E_ROUNDED)})
EXCLUDED_DIRS = frozenset({"_fixtures", "tests", "test"})
DRIVE = re.compile(r"[A-Za-z]:")
DYNAMIC_CALLS = frozenset({"getattr", "hasattr", "setattr", "delattr"})
NAMESPACE_CALLS = frozenset({"vars", "globals", "locals"})
# Relay reads: calls that read or write one member of their first argument, and dunders that expose
# a module's whole namespace.
MEMBER_CALLS = frozenset({"getattr", "setattr", "delattr", "vars"})
NAMESPACE_DUNDERS = frozenset({"__dict__", "__getattribute__", "__getattr__"})
# Any four member reads: what a star import, or an alias no scan follows, can reach.
ANY = (None,) * 4
# Distinct origins followed per alias statement; past that, any member of the read counts as read.
ALIAS_ORIGINS = 8
CODE_CALLS = frozenset({"exec", "eval", "compile"})
# dict methods that write a module namespace reached as vars(x) or x.__dict__.
NAMESPACE_WRITES = frozenset({"update", "setdefault", "pop", "popitem", "clear", "__setitem__", "__delitem__",
                              "__ior__"})
MESH = "atlas.source-bound-exterior-thermal-mesh.v1"
DIFFERENTIAL = "differential-plate-component-partition-v1"
WALL = "atlas.rigid-space-time-wall-measures.v1"
WALL_METHOD = "exact-rational-enclosed-rigid-space-time-wall-v1"
# Every argument of _measure_walls that reaches a persisted value, as stored in its record.
WALL_INPUTS = ("funding_id", "collar_plan_id", "parent_state_id", "source", "start_time_s", "end_time_s",
               "trajectory", "prior_trajectory_id", "trajectory_id", "grid_cell_ids",
               "max_volume_error_m3", "max_leaves")
# WallMeasures.restore: keys every stored record must carry (with measure_id).
WALL_REQUIRED = ("funding_id", "collar_plan_id", "parent_state_id", "source", "start_time_s", "end_time_s",
                 "trajectory", "prior_trajectory_id", "trajectory_id", "start_support_id", "end_support_id",
                 "grid_cell_ids", "rows", "faces", "exterior_cells")
# Every input of the E goal and of _representative_pose, as stored in the mesh header.
E_INPUTS = ("trajectory_id", "trajectory_segments", "endpoint", "max_geometry_volume_error_m3",
            "funding_id", "source")
ROW_SIGNS = (("inward_volume_m3", "inward_bounds_m3", "inward_max_deviation_m3", "inward_exact_volume_m3"),
             ("outward_volume_m3", "outward_bounds_m3", "outward_max_deviation_m3", "outward_exact_volume_m3"))
# Certified enclosures of one true quantity per exterior cell: (pose slots feeding it, disjointness code).
CELL_ENCLOSURES = {
    "start_volume_bounds_m3": (("W.volume-plane-normal",), "W_VOLUME_ENCLOSURES_DISJOINT"),
    "end_volume_bounds_m3": (("W.volume-plane-normal",), "W_VOLUME_ENCLOSURES_DISJOINT"),
    "geometry_volume_change_bounds_m3": (("W.volume-plane-normal",), "W_VOLUME_ENCLOSURES_DISJOINT"),
    "flux_volume_change_bounds_m3": (("W.wall-normal",), "W_FLUX_ENCLOSURES_DISJOINT"),
    "gcl_intersection_bounds_m3": (("W.wall-normal", "W.volume-plane-normal"), "W_GCL_ENCLOSURES_DISJOINT")}
# Chosen allocations and their allowance may legitimately move inside the enclosures.
CELL_DERIVED = {"chosen_volume_change_m3": ("W.wall-normal",),
                "chosen_volume_change_error_m3": ("W.wall-normal",),
                "chosen_change_admissible_bounds_m3": ("W.wall-normal", "W.volume-plane-normal")}
# _measure_walls' record for WALL_METHOD (one writer, identical in both reviewed W sources): exact key
# sets of the record, its rows, faces and exterior cells, and its fixed strings.
WALL_KEYS = frozenset(WALL_REQUIRED) | {"schema", "method", "measure_id", "max_volume_error_m3", "max_leaves",
                                        "support_rule", "scope"}
WALL_FIXED = {"support_rule": ("rotated original actual cone/radial-layer minus fixed full-grid box; "
                               "no endpoint stock resampling"),
              "scope": ("coarse per-source patch/layer FV geometry; rigorous integration bounds; "
                        "no field/time-discretisation accuracy bound")}
WALL_ROW_KEYS = frozenset({"side", "face_index", "cell_id", "exterior_cell_key"} |
                          {name for sign in ROW_SIGNS for name in sign[:3]})
WALL_FACE_KEYS = frozenset({"side", "face_index", "cell_id", "normal_has_constant_sign"} |
                           {sign[3] for sign in ROW_SIGNS})
WALL_CELL_KEYS = frozenset({"exterior_cell_key", "start_support_id", "end_support_id"} |
                           set(CELL_ENCLOSURES) | set(CELL_DERIVED))
# An extension module beside x.py is what Python imports as x.
SHADOW_SUFFIXES = frozenset({".pyd", ".so"})
E_QUAT_PROOF = "E-b-quat-cross-arm-r1"
E_RADIUS_PROOF = "E-b-quat-radius-growth-r1"
FAIL_CODES = frozenset({
    "E_HISTORY_IDENTITY_CONTRADICTION", "W_HISTORY_IDENTITY_CONTRADICTION", "W_MEASURE_ID_CONTRADICTION",
    "W_RECORD_CONTRACT_CONTRADICTION", "W_ROW_CONTRACT_CONTRADICTION", "W_FACE_CLOSURE_CONTRADICTION", "W_CELL_CONTRACT_CONTRADICTION",
    "W_POSE_INDEPENDENT_FACES_CHANGED", "W_FLUX_ENCLOSURES_DISJOINT", "W_VOLUME_ENCLOSURES_DISJOINT",
    "W_GCL_ENCLOSURES_DISJOINT", "W_IDENTICAL_CODE_OUTPUT_CHANGED"})
POSED = "Euclidean radius in the input vector's units"
OPERATOR = "returned operator bound is 4*internal L2 quaternion error"
CALLER_UNITS = "caller's input-vector units (rotation preserves them)"
NORMAL_UNITS = "source cone-normal coordinates (scale-free direction)"
NO_BOUND = ("certified enclosures stay valid (DESIGN section 2); tests on posed values flip only toward "
            "refusal (DESIGN section 3); no propagated cross-arm bound on downstream values")


def _slot(family, sites, join, quantity, units, norm, components, error_meaning, consequence,
          output_field=None, persisted=()):
    return {"family": family, "sites": sites, "join": join, "quantity": quantity, "units": units,
            "norm": norm, "components": components, "output_field": output_field,
            "error_meaning": error_meaning, "persisted": list(persisted), "consequence": consequence}


SLOTS = {
    "W.wall-normal": _slot(
        "W", ((WM, "_wall_leaf", 1),), "wall", "posed cone normal", NORMAL_UNITS, "l2", 3, POSED,
        "wall flux enclosures and allocations (coarse-route wall-measure record)",
        persisted=("rows/*/inward_bounds_m3", "rows/*/outward_bounds_m3", "rows/*/inward_volume_m3",
                   "rows/*/outward_volume_m3", "rows/*/inward_max_deviation_m3",
                   "rows/*/outward_max_deviation_m3", "exterior_cells/*/flux_volume_change_bounds_m3",
                   "exterior_cells/*/gcl_intersection_bounds_m3", "exterior_cells/*/chosen_volume_change_m3",
                   "exterior_cells/*/chosen_volume_change_error_m3",
                   "exterior_cells/*/chosen_change_admissible_bounds_m3")),
    "W.volume-plane-normal": _slot(
        "W", ((WM, "_pose_planes", 1),), "wall", "posed cone normal for volume planes", NORMAL_UNITS, "l2", 3,
        POSED, "endpoint and geometry volume enclosures (coarse-route wall-measure record)",
        persisted=("exterior_cells/*/start_volume_bounds_m3", "exterior_cells/*/end_volume_bounds_m3",
                   "exterior_cells/*/geometry_volume_change_bounds_m3",
                   "exterior_cells/*/gcl_intersection_bounds_m3",
                   "exterior_cells/*/chosen_change_admissible_bounds_m3")),
    "W.inverse-grid-vertex": _slot(
        "W", ((WM, "_measure_walls", 1),), "wall", "inverse-posed grid vertex", "m", "l2", 3, POSED,
        "coverage subdivision and refusal only"),
    "E.representative-quaternion": _slot(
        "E", ((EM, "build_exterior_mesh", 1), (EM, "_build_exterior_mesh_record", 1)), "mesh",
        "representative quaternion", "1", "l2", 4, "stored operator bound is 4*internal L2 quaternion error",
        "rigid exterior mesh pose", output_field="representative_quaternion",
        persisted=("representative_quaternion",)),
    "E.pose-operator-error": _slot(
        "E", ((EM, "build_exterior_mesh", 1), (EM, "_build_exterior_mesh_record", 1)), "mesh",
        "rotation operator error bound", "1", "scalar", 1,
        "rotation operator distance bound; 4*internal quaternion error", "rigid exterior mesh pose bound",
        output_field="pose_operator_error_bound", persisted=("pose_operator_error_bound",)),
    "D.ray-box": _slot(
        "W", ((DG, "_ray_box", 1),), None, "posed ray point (prior history)", CALLER_UNITS, "l2", 3, POSED,
        "differential ray/box tests and enclosures; moving_interface_moments also calls _ray_box"),
    "D.pose-binding": _slot(
        "W", ((DG, "_pose_binding", 1),), None, "endpoint-posed axis (level 24, band test)", CALLER_UNITS,
        "l2", 3, POSED, "band and sign/separation tests"),
    "D.source-planes": _slot(
        "W", ((DG, "_source_planes", 1),), None, "posed source cone normals", CALLER_UNITS, "l2", 3, POSED,
        "differential source-plane enclosures"),
    "D.boundary-leaf": _slot(
        "W", ((DG, "_boundary_leaf", 1),), None, "inverse-posed boundary plane normal (boundary prior)",
        CALLER_UNITS, "l2", 3, POSED, "differential boundary-leaf enclosures"),
    "D.constraint-pose": _slot(
        "W", ((DG, "_constraint_pose", 2),), None, "posed constraint normals", CALLER_UNITS, "l2", 3, POSED,
        "differential constraint enclosures"),
    "D.posed-boundary": _slot(
        "E", ((DG, "posed_boundary", 1),), None, "posed-boundary rotation quaternion", "1", "l2", 4, OPERATOR,
        "posed boundary rotation and its exact axis certificate (pressure axis route)"),
    "P.current-force-pose": _slot(
        "E", ((CFP, "current_force_pose", 1),), None, "force-pose quaternion", "1", "l2", 4, OPERATOR,
        "force/matrix error terms and torque/power checks (refusal-only flips)"),
    "W.unreviewed-access": _slot(
        "W", (), None, "unreviewed W._pose_vector access", "unknown", "unknown", 0, "unknown",
        "unknown: outside the reviewed call-site table"),
    "E.unreviewed-access": _slot(
        "E", (), None, "unreviewed E._representative_pose access", "unknown", "unknown", 0, "unknown",
        "unknown: outside the reviewed call-site table"),
}
QUANTITY_KEYS = ("quantity", "units", "norm", "components", "error_meaning")
# (caller module, caller qualname, family) -> (reviewed call count, slots it feeds)
SITE_TABLE = {}
for _name, _row in SLOTS.items():
    for _module, _caller, _count in _row["sites"]:
        SITE_TABLE.setdefault((_module, _caller, _row["family"]), (_count, []))[1].append(_name)
_CATALOGS = {}


class ProvenanceError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise ProvenanceError(message)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def code_of(issue):
    parts = issue.split(":")
    return parts[-2] if len(parts) > 1 and parts[-1].isdigit() else parts[-1]


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def decoded(raw):
    def bad_constant(value):
        raise ProvenanceError("nonfinite JSON constant: " + value)
    need(type(raw) is bytes, "exact raw bytes required")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=bad_constant)
    except (ValueError, UnicodeError) as error:
        raise ProvenanceError("record JSON invalid: " + str(error)) from error


def rational(value, where):
    need(type(value) is list and len(value) == 2 and all(type(q) is str and HEX.fullmatch(q) for q in value),
         "source-defined exact encoding differs: " + where)
    numerator, denominator = int(value[0], 16), int(value[1], 16)
    need(denominator > 0 and max(abs(numerator).bit_length(), denominator.bit_length()) <= MAX_BITS,
         "exact rational outside the 1 MiB integer limit: " + where)
    return Fraction(numerator, denominator)


def key_parts(path):
    """Parts of a canonical relative inventory key (native-root-relative POSIX); None otherwise."""
    if type(path) is not str or not path or "\\" in path or "\0" in path or path.startswith("/") or \
            DRIVE.match(path):
        return None
    parts = tuple(path.split("/"))
    return None if any(part in ("", ".", "..") for part in parts) else parts


def _excluded(path):
    """Test/fixture paths below the package directory. A malformed key is never excluded: the
    catalog refuses it, so no ancestor directory name can drop a package module from the scan."""
    parts = key_parts(path)
    if parts is None:
        return False
    inner = parts[1:] or parts
    return bool(EXCLUDED_DIRS & set(inner[:-1])) or inner[-1].startswith("test_")


def source_paths(inventory):
    """Every selected package module the scan covers, without selecting a source on the caller's behalf."""
    need(isinstance(inventory, Mapping), "source inventory must be a mapping")
    return sorted(path for path in inventory if type(path) is str and path.endswith(".py")
                  and not _excluded(path))


def _dotted_module(path):
    """Python module name of a canonical inventory key (package/x.py -> package.x)."""
    parts = list(key_parts(path))
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _shadow_name(path):
    """Module name a non-source key claims ahead of a .py module of that name: an extension module, or
    a package __init__ of another importable suffix (Python's finder tries packages, then extensions,
    before source). None for anything else, including __pycache__ entries."""
    parts = key_parts(path)
    if not parts or "__pycache__" in parts:
        return None
    base, dot, _ = parts[-1].partition(".")
    if dot and "." + parts[-1].rsplit(".", 1)[-1] in SHADOW_SUFFIXES:
        return ".".join(parts[:-1] + (() if base == "__init__" else (base,)))
    if parts[-1] in ("__init__.pyw", "__init__.pyc"):
        return ".".join(parts[:-1])
    return None


def _family_of(name):
    stem = (name or "").rsplit(".", 1)[-1]
    return next((family for family, (module, _) in PRODUCERS.items() if stem == module), None)


# Only text attributes stay inert: __name__ and __file__ re-import or re-load the module unnamed.
INERT_DUNDERS = frozenset({"__qualname__", "__doc__", "__package__"})


def producer_closure(tree, family):
    """Producer-module bindings that reach the producer -> every binding each one reaches (itself included).

    Name-level and flow-insensitive: a binding is a module-level def, class or assignment target, and a
    class is one unit (its methods reach each other through self). Every binding of a reused name merges."""
    producer = PRODUCERS[family][1]
    edges = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            targets, value = [node.name], node
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            found = node.targets if isinstance(node, ast.Assign) else [node.target]
            targets = [sub.id for target in found for sub in ast.walk(target) if isinstance(sub, ast.Name)]
            value = node.value
        else:
            continue
        names = {sub.id for sub in ast.walk(value) if isinstance(sub, ast.Name)} if value is not None else set()
        for target in targets:
            edges.setdefault(target, set()).update(names - {target})
    reach, grown = {producer}, True
    while grown:
        grown = False
        for name, names in edges.items():
            if name not in reach and names & reach:
                reach.add(name)
                grown = True
    reach.discard(producer)

    def reachable(start):
        seen, todo = set(), [start]
        while todo:
            name = todo.pop()
            if name not in seen:
                seen.add(name)
                todo.extend(edges.get(name, set()) & reach)
        return sorted(seen)
    return {name: reachable(name) for name in sorted(reach)}


def module_imports(nodes, path):
    """Absolute name -> first line of every module one module may import (relative imports resolved;
    parent packages and from-imported names included, since either can be a module)."""
    package = _dotted_module(path).split(".")
    if key_parts(path)[-1] != "__init__.py":
        package = package[:-1]
    names = {}

    def add(candidates, line):
        for name in candidates:
            names[name] = min(names.get(name, line), line)
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                add((".".join(parts[:index]) for index in range(1, len(parts)+1)), node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level-1 > len(package):
                continue
            stem = (package[:len(package)-(node.level-1)] if node.level else []) + \
                (node.module.split(".") if node.module else [])
            add((".".join(stem[:index]) for index in range(1, len(stem)+1)), node.lineno)
            add((".".join(stem+[alias.name]) for alias in node.names if alias.name != "*"), node.lineno)
    return names


def _scope_of(node, parents):
    """Nearest enclosing function, lambda or class of node (None at module level)."""
    return next((scope for scope in _ancestors(node, parents) if isinstance(
        scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))), None)


def _module_binding(node, name, parents):
    """True when the import at node binds name outside a function: at module or class level, or in a
    function that declares the name global."""
    scope = _scope_of(node, parents)
    if scope is None or isinstance(scope, ast.ClassDef):
        return True
    return any(isinstance(sub, ast.Global) and name in sub.names and _scope_of(sub, parents) is scope
               for sub in ast.walk(scope))


def _links(imports, parents, path, scanned):
    """Import bindings of one module to selected modules: (local -> specs, module-scope local -> specs,
    [(selected module, line)] of star imports).

    A spec is ("producer", family) for a producer module, ("module", dotted) for another selected module,
    or ("from", dotted, name) for a name imported from a selected module."""
    package = _dotted_module(path).split(".")
    if key_parts(path)[-1] != "__init__.py":
        package = package[:-1]
    links, exports, stars = {}, {}, []
    for node in imports:
        pairs = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name if alias.asname else alias.name.split(".")[0]
                pairs.append((alias.asname or target, target, ""))
        elif not (node.level and node.level-1 > len(package)):
            base = ".".join((package[:len(package)-(node.level-1)] if node.level else []) +
                            (node.module.split(".") if node.module else []))
            pairs.extend((alias.asname or alias.name, (base + "." if base else "") + alias.name, base)
                         for alias in node.names if alias.name != "*")
            if base in scanned and any(alias.name == "*" for alias in node.names):
                stars.append((base, node.lineno))
        for local, target, base in pairs:
            if target in scanned:
                spec = ("producer", _family_of(target)) if _family_of(target) else ("module", target)
            elif base in scanned:
                spec = ("from", base, target.rsplit(".", 1)[-1])
            else:
                continue
            links.setdefault(local, []).append(spec)
            if _module_binding(node, local, parents):
                exports.setdefault(local, []).append(spec)
    return links, exports, stars


def _module_name(node, own, package, names=None):
    """A module name fixed by the source text: a string, __name__, __package__, __package__ + a string,
    or link.__name__ for a local name bound to one selected module (names: local -> dotted name)."""
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.Name) and node.id in ("__name__", "__package__"):
        return own if node.id == "__name__" else package
    if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and isinstance(node.left, ast.Name) and
            node.left.id == "__package__" and isinstance(node.right, ast.Constant) and type(node.right.value) is str):
        return package + node.right.value
    if (isinstance(node, ast.Attribute) and node.attr == "__name__" and isinstance(node.value, ast.Name) and
            node.value.id in (names or {})):
        return names[node.value.id]
    return None


def _import_root(node, scanned, own="", package="", bound=None):
    """The selected modules a read by fixed name can return, as link specs ([] if none):
    importlib.import_module, __import__, sys.modules[name] and sys.modules.get(name), also through local
    names bound to these (bound: see _root_bindings). own and package are this module's dotted name and
    package, for __name__, __package__ and relative names; a relative name whose package or level is not
    fixed by the text can be any selected module of that name."""
    bound = bound or {}

    def modules(value):
        return (isinstance(value, ast.Attribute) and value.attr == "modules" or
                isinstance(value, ast.Name) and value.id in bound.get("modules", ()))

    kind, arg, func = None, None, node.func if isinstance(node, ast.Call) else None
    if isinstance(node, ast.Subscript) and modules(node.value):
        kind, arg = "modules", node.slice
    elif func is not None and node.args:
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if (called == "get" and isinstance(func, ast.Attribute) and modules(func.value) or
                isinstance(func, ast.Name) and func.id in bound.get("get", ())):
            kind, arg = "modules", node.args[0]
        elif called in ("import_module", "__import__"):
            kind, arg = called, node.args[0]
        elif isinstance(func, ast.Name) and func.id in bound.get("importers", {}):
            kind, arg = bound["importers"][func.id], node.args[0]
    if kind is None:
        return []
    name = _module_name(arg, own, package, bound.get("names"))
    if name is None:
        return []
    keywords = {k.arg: k.value for k in node.keywords if k.arg} if func is not None else {}
    level, anchor, names = 0, package, [name]
    if kind == "import_module" and name.startswith("."):
        level, names = len(name) - len(name.lstrip(".")), [name.lstrip(".")]
        given = keywords.get("package", node.args[1] if len(node.args) > 1 else None)
        if given is not None:
            anchor = _module_name(given, own, package, bound.get("names"))
    elif kind == "__import__":
        given = keywords.get("level", node.args[4] if len(node.args) > 4 else None)
        if given is not None:
            fixed = isinstance(given, ast.Constant) and type(given.value) is int
            level, anchor = (given.value, package) if fixed else (1, None)
        fromlist = keywords.get("fromlist", node.args[3] if len(node.args) > 3 else None)
        top = name.split(".")[0]      # __import__ returns the top package unless a fromlist is given
        if fromlist is None or isinstance(fromlist, (ast.List, ast.Tuple)) and not fromlist.elts:
            names = [top]
        elif not isinstance(fromlist, (ast.List, ast.Tuple, ast.Set)):
            names = sorted({top, name})
    if level and anchor is None:
        found = {module for module in scanned for tail in names if tail and module.endswith("." + tail)}
    elif level:
        base = anchor.split(".") if anchor else []
        if level - 1 > len(base):
            return []
        found = {".".join(base[:len(base) - (level - 1)] + ([tail] if tail else [])) for tail in names}
    else:
        found = set(names)
    return [("producer", _family_of(module)) if _family_of(module) else ("module", module)
            for module in sorted(found) if module in scanned]


def _root_bindings(nodes, links, modules_of):
    """Local names that a from-import or a simple assignment (followed to a fixed point) binds to
    importlib.import_module or __import__ ("importers"), sys.modules ("modules") or sys.modules.get
    ("get"); and the links naming one selected module ("names", for link.__name__)."""
    importers, maps, getters = {}, set(), set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                pair, local = (node.module, alias.name), alias.asname or alias.name
                if pair in (("importlib", "import_module"), ("builtins", "__import__")):
                    importers[local] = alias.name
                elif pair == ("sys", "modules"):
                    maps.add(local)
    assigns = [(node.targets[0].id, node.value) for node in nodes if isinstance(node, ast.Assign) and
               len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)]
    assigns += [(node.target.id, node.value) for node in nodes if isinstance(node, ast.AnnAssign) and
                isinstance(node.target, ast.Name) and node.value is not None]
    assigns = [(local, value) for local, value in assigns if isinstance(value, (ast.Name, ast.Attribute))]
    changed = True
    while changed:
        changed = False
        for local, value in assigns:
            attr = value.attr if isinstance(value, ast.Attribute) else None
            ident = value.id if isinstance(value, ast.Name) else None
            if local not in importers and (attr in ("import_module", "__import__") or ident == "__import__" or
                                           ident in importers):
                importers[local], changed = importers.get(ident) or attr or ident, True
            elif local not in maps and (attr == "modules" or ident in maps):
                maps.add(local)
                changed = True
            elif local not in getters and (ident in getters or attr == "get" and (
                    isinstance(value.value, ast.Attribute) and value.value.attr == "modules" or
                    isinstance(value.value, ast.Name) and value.value.id in maps)):
                getters.add(local)
                changed = True
    names = {}
    for local, specs in links.items():
        dotted = {spec[1] if spec[0] == "module" else modules_of.get(spec[1]) for spec in specs}
        if len(dotted) == 1 and all(spec[0] in ("module", "producer") for spec in specs) and None not in dotted:
            names[local] = dotted.pop()
    return {"importers": importers, "modules": maps, "get": getters, "names": names}


def _held_name(node):
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _is_text(node, texts=frozenset()):
    """A string, bytes or f-string written into the module, or a name or attribute in texts."""
    return (isinstance(node, ast.JoinedStr) or isinstance(node, ast.Constant) and type(node.value) in (str, bytes)
            or _held_name(node) in texts)


def _text_names(nodes):
    """Names and attribute names that an assignment anywhere in the module binds to source text, followed
    to a fixed point: exec(_T) and exec(K.T) run that text as surely as exec('...') does."""
    held = [(target, node.value) for node in nodes if isinstance(node, ast.Assign) for target in node.targets]
    held += [(node.target, node.value) for node in nodes
             if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and node.value is not None]
    held = [(_held_name(target), value) for target, value in held if _held_name(target)]
    texts, changed = set(), True
    while changed:
        changed = False
        for name, value in held:
            if name not in texts and _is_text(value, texts):
                texts.add(name)
                changed = True
    return texts


def _code_text(call, texts=frozenset()):
    """exec, eval or compile of source text written into the module (see _is_text)."""
    func = call.func
    name = func.id if isinstance(func, ast.Name) else (
        func.attr if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and
        func.value.id in ("builtins", "__builtins__") else None)
    text = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "source"), None)
    return name in CODE_CALLS and _is_text(text, texts)


def scan_module(raw, own=None, closures=None):
    """Producer call sites, unreviewed producer accesses and consequence routes in one module.

    Static and conservative (see the module docstring for every surfaced form). Returns
    (tree, sites, unresolved, routes); routes are references to producer-module bindings that reach the
    producer (closures: family -> producer_closure), made from outside that producer's module."""
    return _scan(raw, own, closures)[:4]


def _scan(raw, own, closures, path=None, scanned=frozenset()):
    """scan_module plus, with path and the selected dotted module names: the import statements, this
    module's module-scope import bindings (exports) and the chains it reads through bindings to other
    selected modules (relays), for compile_catalog to resolve across modules."""
    tree = ast.parse(raw)
    # One breadth-first pass, in ast.walk's order, gives every later pass its nodes and parents.
    nodes, parents, index = [tree], {}, 0
    while index < len(nodes):
        for child in ast.iter_child_nodes(nodes[index]):
            parents[child] = nodes[index]
            nodes.append(child)
        index += 1
    closures = closures or {}
    modules, functions, unresolved, routes, relays = {}, {}, [], [], []

    def caller(node):
        names = []
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
            elif isinstance(node, ast.Lambda):
                names.append("<lambda>")
        return ".".join(reversed(names)) or "<module>"

    def route(family, member, node):
        routes.append({"family": family, "member": member, "caller": caller(node), "line": node.lineno})

    imports = [node for node in nodes if isinstance(node, (ast.Import, ast.ImportFrom))]
    links, exports, stars = _links(imports, parents, path, scanned) if path else ({}, {}, [])
    own_name = _dotted_module(path) if path else ""
    package = own_name if path and key_parts(path)[-1] == "__init__.py" else own_name.rpartition(".")[0]
    producer_modules = {_family_of(name): name for name in scanned if _family_of(name)}
    roots = _root_bindings(nodes, links, producer_modules)
    texts = _text_names(nodes)

    def module_alias(node, alias):
        family = _family_of(alias.name)
        modules[alias.asname or alias.name] = family
        # A class attribute holding a producer module is read as C.alias, which no scan follows.
        if isinstance(_scope_of(node, parents), ast.ClassDef):
            unresolved.append((family, node.lineno, "PRODUCER_REEXPORTED"))

    for node in imports:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _family_of(alias.name):
                    module_alias(node, alias)
        elif isinstance(node, ast.ImportFrom):
            source = _family_of(node.module)
            for alias in node.names:
                if source and alias.name == "*":
                    unresolved.append((source, node.lineno, "STAR_IMPORT_FROM_PRODUCER_MODULE"))
                elif source and alias.name == PRODUCERS[source][1]:
                    functions[alias.asname or alias.name] = source
                    # A module-, class- or global-declared binding re-exports the producer under a name no
                    # scan follows.
                    if source != own and _module_binding(node, alias.asname or alias.name, parents):
                        unresolved.append((source, node.lineno, "PRODUCER_REEXPORTED"))
                elif alias.name in PRODUCER_NAMES:
                    unresolved.append((PRODUCER_NAMES[alias.name], node.lineno,
                                       "PRODUCER_NAME_IMPORTED_FROM_NON_PRODUCER"))
                elif source and source != own and alias.name in closures.get(source, ()):
                    route(source, alias.name, node)
                elif not source and _family_of(alias.name):
                    module_alias(node, alias)
    if own:
        functions.setdefault(PRODUCERS[own][1], own)
    bound = sorted(set(functions.values()) | set(modules.values()))

    def receiver(node):
        # A producer module is a bound alias or any attribute chain whose last part is its stem, whatever
        # the chain hangs from (__import__("pkg").stem and getattr(x, "y").stem included).
        if isinstance(node, ast.Name):
            return modules.get(node.id) or STEMS.get(node.id)
        if isinstance(node, ast.Attribute) and node.attr in STEMS:
            return STEMS[node.attr]
        return None

    calls = {id(node.func): node for node in nodes if isinstance(node, ast.Call)}
    sites = []
    for node in nodes:
        if isinstance(node, ast.Constant) and type(node.value) in (str, bytes):
            # Docstrings included: __doc__ and inspect read them back as text.
            text = node.value if type(node.value) is str else node.value.decode("latin-1")
            for name, family in PRODUCER_NAMES.items():
                if name in text:
                    unresolved.append((family, node.lineno, "PRODUCER_NAME_STRING"))
            for family, (stem, _) in PRODUCERS.items():
                if stem in text:
                    unresolved.append((family, node.lineno, "PRODUCER_MODULE_NAME_STRING"))
            continue
        if isinstance(node, ast.Call) and _code_text(node, texts):
            # Source text run in place can read or write any module; no scan follows it.
            unresolved.extend((family, node.lineno, "DYNAMIC_CODE_TEXT") for family in PRODUCERS)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name in DYNAMIC_CALLS and node.args and receiver(node.args[0]):
                family = receiver(node.args[0])
                literal = (len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and
                           type(node.args[1].value) is str and node.args[1].value not in PRODUCER_NAMES)
                if not literal:
                    unresolved.append((family, node.lineno, "DYNAMIC_PRODUCER_MODULE_ACCESS"))
                elif family != own and node.args[1].value in closures.get(family, ()):
                    route(family, node.args[1].value, node)
            elif name == "vars" and node.args and receiver(node.args[0]):
                unresolved.append((receiver(node.args[0]), node.lineno, "DYNAMIC_PRODUCER_MODULE_ACCESS"))
            elif name in NAMESPACE_CALLS and not node.args:
                unresolved.extend((family, node.lineno, "DYNAMIC_PRODUCER_NAMESPACE_ACCESS") for family in bound)
            continue
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load) and receiver(node):
            # A producer module may only be an attribute base; anything else lets it escape the scan.
            family, parent = receiver(node), parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.value is node:
                if parent.attr.startswith("__") and parent.attr not in INERT_DUNDERS:
                    unresolved.append((family, node.lineno, "DYNAMIC_PRODUCER_MODULE_ACCESS"))
                elif family != own and parent.attr in closures.get(family, ()):
                    route(family, parent.attr, parent)
            elif not (isinstance(parent, ast.Call) and parent.args and parent.args[0] is node and
                      isinstance(parent.func, ast.Name) and parent.func.id in DYNAMIC_CALLS | {"vars"}):
                unresolved.append((family, node.lineno, "PRODUCER_MODULE_ESCAPES"))
        if isinstance(node, ast.Attribute) and node.attr in PRODUCER_NAMES:
            family = receiver(node.value)
            if family != PRODUCER_NAMES[node.attr]:
                unresolved.append((PRODUCER_NAMES[node.attr], node.lineno, "UNRESOLVED_PRODUCER_ATTRIBUTE"))
                continue
        elif isinstance(node, ast.Name) and node.id in functions:
            family = functions[node.id]
        elif isinstance(node, ast.Name) and node.id in PRODUCER_NAMES:
            unresolved.append((PRODUCER_NAMES[node.id], node.lineno, "UNRESOLVED_PRODUCER_NAME"))
            continue
        else:
            continue
        call = calls.get(id(node))
        if call is None:
            unresolved.append((family, node.lineno, "PRODUCER_REFERENCED_NOT_CALLED"))
            continue
        sites.append({"family": family, "caller": caller(call), "line": call.lineno,
                      "end_line": call.end_lineno, "column": call.col_offset,
                      "ast_sha256": sha256(ast.dump(call, include_attributes=False).encode()).hexdigest()})

    def chain(node):
        """(member names read upward from node, the top node of that read). None marks a computed name or
        namespace access; another dunder or anything but a member read ends the read."""
        names = []
        while True:
            parent = parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.value is node:
                if parent.attr in NAMESPACE_DUNDERS:
                    return names + [None], parent
                if parent.attr.startswith("__"):
                    return names, node
                names.append(parent.attr)
            elif (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.args and
                  parent.args[0] is node and parent.func.id in MEMBER_CALLS):
                literal = (parent.func.id != "vars" and len(parent.args) > 1 and
                           isinstance(parent.args[1], ast.Constant) and type(parent.args[1].value) is str)
                names.append(parent.args[1].value if literal else None)
                if parent.func.id != "getattr" or not literal:
                    return names, parent
            else:
                return names, node
            node = parent

    def alias_of(top):
        """Target name and statement of a simple assignment whose whole value is top."""
        parent = parents.get(top)
        if isinstance(parent, ast.Assign) and parent.value is top and len(parent.targets) == 1 and \
                isinstance(parent.targets[0], ast.Name):
            return parent.targets[0].id, parent
        if isinstance(parent, ast.AnnAssign) and parent.value is top and isinstance(parent.target, ast.Name):
            return parent.target.id, parent
        return None, None

    def fixed_root(node):
        return _import_root(node, scanned, own_name, package, roots)

    # Reads through another selected module's bindings (relays): from names bound to a selected module or
    # to a name in one, from reads through a producer module's own bindings (E.W), from reads of a module
    # by fixed name and from star imports, following simple assignments of such a read to every load of
    # the assigned name the binding can reach. compile_catalog resolves each read.
    loads = {}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loads.setdefault(node.id, []).append(node)
    pending = [(node, spec) for name, uses in loads.items() for spec in links.get(name, ()) for node in uses]
    pending += [(node, spec) for node in nodes if isinstance(node, (ast.Call, ast.Subscript))
                for spec in fixed_root(node)]
    # A star import binds every public name of a selected module: any producer module within four
    # member reads of its namespace counts as read by a computed name.
    relays.extend((("module", base), ANY, line) for base, line in stars if not _family_of(base))
    nonlocals = {(_scope_of(sub, parents), name) for sub in nodes if isinstance(sub, ast.Nonlocal)
                 for name in sub.names}
    aliases, held, followed, origins = set(), set(), set(), {}
    while pending:
        node, spec = pending.pop()
        steps, top = chain(node)
        if spec[0] == "producer" and isinstance(node, ast.Name):
            # A producer module bound here: its own members are the scan's above; a read through one of
            # its bindings (E.W.member) is a relay.
            if not steps:
                continue
            spec, steps = ("from", producer_modules[spec[1]], steps[0]), steps[1:]
        name, statement = alias_of(top)
        if name is not None and (statement, spec) in followed:
            continue
        depth, inner = 0, spec
        while inner[0] == "chain":
            depth, inner = depth + 1, inner[1]
        in_class = name is not None and isinstance(_scope_of(statement, parents), ast.ClassDef)
        if name is not None and (in_class or depth >= 3 or origins.get(statement, 0) >= ALIAS_ORIGINS):
            # A class attribute is read as C.name or self.name, which no scan follows (writes through one
            # are caught below); aliases of aliases are followed three deep and each statement for
            # ALIAS_ORIGINS origins. Past any of these, any member counts as read.
            if in_class:
                held.add(name)
            name, steps = None, steps + list(ANY)
        if name is None:
            if spec[0] != "module" or steps:
                relays.append((spec, tuple(steps), node.lineno))
            continue
        followed.add((statement, spec))
        origins[statement] = origins.get(statement, 0) + 1
        aliases.add(name)
        origin, wide = ("chain", spec, tuple(steps)), _module_binding(statement, name, parents)
        scope = _scope_of(statement, parents)
        while scope is not None and (scope, name) in nonlocals:
            # A nonlocal name is bound in the enclosing function that owns it.
            scope = next((outer for outer in _ancestors(scope, parents) if isinstance(
                outer, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))), None)
        if wide:
            exports.setdefault(name, []).append(origin)
        pending.extend((use, origin) for use in loads.get(name, ())
                       if wide or scope is None or scope in _ancestors(use, parents))

    def anchored(node):
        # Hangs (through attributes, items, vars(x) and getattr(x, ...)) from a selected module read by
        # fixed name, a binding to a selected module or a name in one, an alias of a read through one, a
        # class attribute holding such a read, a producer module or a producer function.
        while not fixed_root(node):
            if isinstance(node, (ast.Attribute, ast.Subscript)):
                if isinstance(node, ast.Attribute) and node.attr in held:
                    return True
                node = node.value
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.args and
                  node.func.id in ("vars", "getattr")):
                node = node.args[0]
            else:
                return isinstance(node, ast.Name) and (node.id in links or node.id in aliases or
                                                       node.id in functions or bool(receiver(node)))
        return True

    def writes(node):
        # Attribute or item assignment or deletion, setattr/delattr, operator.setitem/delitem, the
        # __setattr__/__delattr__/__setitem__/__delitem__ methods, or a dict method writing vars(x)/x.__dict__.
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            return anchored(node.value) or bool(fixed_root(node))
        if not isinstance(node, ast.Call):
            return False
        func, first = node.func, node.args[0] if node.args else None
        if isinstance(func, ast.Name) and func.id in ("setattr", "delattr", "setitem", "delitem") or (
                isinstance(func, ast.Attribute) and func.attr in ("setitem", "delitem") and
                isinstance(func.value, ast.Name) and func.value.id == "operator"):
            return first is not None and anchored(first)
        if isinstance(func, ast.Attribute) and func.attr in ("__setattr__", "__delattr__", "__setitem__",
                                                             "__delitem__"):
            return anchored(func.value) or (first is not None and anchored(first))
        namespace = func.value if isinstance(func, ast.Attribute) and func.attr in NAMESPACE_WRITES else None
        return namespace is not None and (
            isinstance(namespace, ast.Attribute) and namespace.attr == "__dict__" or
            isinstance(namespace, ast.Call) and isinstance(namespace.func, ast.Name) and
            namespace.func.id == "vars") and anchored(namespace)

    for node in nodes:
        # A write into a package module or an object imported from one, or a replacement of a selected
        # module in sys.modules, can change any producer's inputs.
        if writes(node):
            unresolved.extend((family, node.lineno, "PACKAGE_MODULE_MUTATED") for family in PRODUCERS)
    return (tree, sorted(sites, key=lambda site: (site["line"], site["column"])), sorted(set(unresolved)),
            sorted(routes, key=lambda row: (row["line"], row["family"], row["member"], row["caller"])), imports,
            exports, sorted(set(relays), key=repr))


def _ancestors(node, parents):
    while node in parents:
        node = parents[node]
        yield node


def compile_catalog(source_pins, source_bytes):
    """Check full selected source bytes, then derive producers, every call site, unreviewed accesses,
    consequence routes and each producer's package import closure."""
    paths = source_paths(source_pins)
    need(isinstance(source_bytes, Mapping) and set(source_bytes) == set(paths),
         "provide exactly the selected package source bytes")
    for path in paths:
        need(key_parts(path) is not None, "source inventory key is not canonical and relative: " + repr(path))
        expected, raw = source_pins[path], source_bytes[path]
        need(type(expected) is str and SHA.fullmatch(expected), "invalid selected source pin")
        need(type(raw) is bytes and sha256(raw).hexdigest() == expected, "selected source bytes differ: " + path)
    names = [PurePosixPath(path).name for path in paths]
    for name in (WM, EM, DG, CFP):
        need(names.count(name) <= 1, "ambiguous selected module: " + name)
    modules = sorted(path for path in source_pins if type(path) is str and path.endswith(".py") and key_parts(path))
    # Python imports a package (x/__init__.*) or an extension module ahead of x.py: two keys that import
    # as one module, or a non-source file claiming a scanned name, would run bytes other than those scanned.
    dotted = {}
    for path in modules:
        need(_dotted_module(path) not in dotted, "two selected sources import as one module: " + path)
        dotted[_dotted_module(path)] = path
    scanned = frozenset(_dotted_module(path) for path in paths)
    for path in source_pins:
        need(_shadow_name(path) not in scanned, "selected source shadowed by a non-source module: " + str(path))
    key = digest([sorted((path, source_pins[path]) for path in paths), modules])
    if key in _CATALOGS:
        return deepcopy(_CATALOGS[key])
    # Producer closures first, so a reference from any other module to one of them is a route.
    closures = {MODULES[module]: producer_closure(ast.parse(source_bytes[path]), MODULES[module])
                for path, module in zip(paths, names, strict=True) if module in MODULES}
    producers, sites, unresolved, routes, imports, exports, relays = {}, [], [], [], {}, {}, []
    for path, module in zip(paths, names, strict=True):
        expected = source_pins[path]
        own = MODULES.get(module)
        tree, found, accesses, reached, statements, exported, relayed = _scan(source_bytes[path], own, closures,
                                                                              path, scanned)
        exports[_dotted_module(path)] = exported
        relays.extend((path, module, expected, spec, steps, line) for spec, steps, line in relayed)
        routes.extend(dict(row, path=path, module=module, sha256=expected,
                           reaches=closures[row["family"]][row["member"]]) for row in reached)
        targets = {dotted[name]: line for name, line in module_imports(statements, path).items() if name in dotted}
        targets.pop(path, None)
        imports[path] = sorted(targets)
        # An excluded test/fixture module is outside the scan, so importing one could relay a producer.
        accesses = list(accesses) + [(family, line, "IMPORT_FROM_EXCLUDED_PATH")
                                     for target, line in sorted(targets.items()) if _excluded(target)
                                     for family in PRODUCERS]
        if own:
            symbol = PRODUCERS[own][1]
            definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == symbol]
            row = {"path": path, "sha256": expected, "known": expected in KNOWN[own], "definition": None}
            if len(definitions) == 1:
                node = definitions[0]
                row["definition"] = {"symbol": symbol, "line": node.lineno, "end_line": node.end_lineno,
                                     "ast_sha256": sha256(ast.dump(node, include_attributes=False)
                                                          .encode()).hexdigest()}
            need(row["definition"] is not None or not row["known"],
                 "pinned source producer definition missing/ambiguous")
            producers[own] = row
        ordinals = {}
        for site in found:
            ordinal = ordinals[(site["caller"], site["family"])] = ordinals.get((site["caller"], site["family"]), 0)+1
            sites.append(dict(site, path=path, module=module, sha256=expected, ordinal=ordinal))
        unresolved.extend({"family": family, "path": path, "module": module, "sha256": expected,
                           "line": line, "code": code} for family, line, code in sorted(set(accesses)))
        del tree

    producer_modules = {MODULES[name]: _dotted_module(path) for path, name in zip(paths, names, strict=True)
                        if name in MODULES}
    submodules = {}
    for sub in sorted(scanned):
        submodules.setdefault(sub.rpartition(".")[0], []).append(sub)

    def reach(spec, steps):
        """(family, member names read after it) for each producer module a relay read reaches, through
        selected modules' bindings and submodules, producer modules' own bindings included (E.W). At the
        root, a producer member imported by name (from .E import x) is the per-module scan's."""
        found, seen, todo = set(), set(), [(spec, tuple(steps), True)]
        while todo:
            spec, steps, root = todo.pop()
            if spec[0] == "chain":
                todo.append((spec[1], spec[2] + steps, root))
                continue
            if spec[0] == "producer":
                found.add((spec[1], steps))
                family, module = spec[1], producer_modules.get(spec[1])
                if module is None or not steps:
                    continue
                name, rest = steps[0], steps[1:]
            else:
                if spec[0] == "from":
                    module, name, rest = spec[1], spec[2], steps
                elif steps:
                    module, name, rest = spec[1], steps[0], steps[1:]
                else:
                    continue
                family = _family_of(module)
                if family and not root:
                    # A producer module's member reached through another module's binding reads as E.name.
                    todo.append((("producer", family), (name,) + rest, False))
                    continue
            # A member named by a producer stem is read as that producer module by the per-module scan;
            # a repeated step adds nothing (import cycles included).
            if (name is not None and name in STEMS) or (module, name, rest) in seen:
                continue
            seen.add((module, name, rest))
            todo.extend((row, rest, False) for local, rows in exports.get(module, {}).items()
                        if name in (None, local) for row in rows)
            if not family:
                todo.extend((("producer", _family_of(sub)) if _family_of(sub) else ("module", sub), rest, False)
                            for sub in submodules.get(module, ()) if name in (None, sub.rpartition(".")[2]))
        return found

    # A producer module read through another module's binding (X.W.member, E.W.member, from .X import W,
    # an alias of either, getattr(X, name)) is judged as a direct read would be: the module itself, a
    # computed member, the producer or a member of its closure is unreviewed; any other member is not.
    relayed, reached = set(), {}
    for path, module, expected, spec, steps, line in relays:
        if (spec, steps) not in reached:
            reached[(spec, steps)] = reach(spec, steps)
        for family, rest in reached[(spec, steps)]:
            if not rest or rest[0] is None or rest[0] == PRODUCERS[family][1] or rest[0] in closures.get(family, ()):
                relayed.add((family, path, module, expected, line))
    unresolved.extend({"family": family, "path": path, "module": module, "sha256": expected, "line": line,
                       "code": "PRODUCER_MODULE_RELAYED"} for family, path, module, expected, line in relayed)
    unresolved.sort(key=lambda row: (row["path"], row["family"], row["line"], row["code"]))
    dependencies = {}
    for family, row in producers.items():
        seen, todo = set(), [row["path"]]
        while todo:
            path = todo.pop()
            if path not in seen:
                seen.add(path)
                todo.extend(imports.get(path, ()))
        dependencies[family] = sorted(seen)
    catalog = {"producers": producers, "sites": sites, "unresolved": unresolved, "routes": routes,
               "dependencies": dependencies, "module_names": sorted(names)}
    if len(_CATALOGS) >= 4:
        _CATALOGS.clear()
    _CATALOGS[key] = deepcopy(catalog)
    return catalog


def classify(catalog):
    """Reviewed slot -> this arm's call sites; every other call site is unreviewed."""
    grouped = {}
    for site in catalog["sites"]:
        grouped.setdefault((site["module"], site["caller"], site["family"]), []).append(site)
    assigned, unreviewed = {slot: [] for slot in SLOTS}, []
    for key, rows in sorted(grouped.items()):
        count, slots = SITE_TABLE.get(key, (None, ()))
        if count == len(rows):
            for slot in slots:
                assigned[slot].extend(rows)
        else:
            unreviewed.extend(rows)
    return assigned, unreviewed


def wall_records(record):
    """Concrete paths of every W record inside one reader-bound record; never a wildcard pairing."""
    found, pending = [], [((), record)]
    while pending:
        path, value = pending.pop()
        if type(value) is dict:
            if value.get("schema") == WALL:
                found.append((path, value))
                continue
            pending.extend((path + (key,), child) for key, child in value.items())
        elif type(value) is list:
            pending.extend((path + (str(index),), child) for index, child in enumerate(value))
    return sorted(found, key=lambda item: item[0])


def _restorable(value):
    """WallMeasures.restore's value rule: string keys; dict, list, str, int or bool values only."""
    stack = [value]
    while stack:
        item = stack.pop()
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                return False
            stack.extend(item.values())
        elif type(item) is list:
            stack.extend(item)
        elif type(item) not in (str, int, bool):
            return False
    return True


def wall_summary(value):
    """Compact exact view of one W record plus its own source-contract contradictions."""
    issues = []

    def exact(raw, where):
        number = rational(raw, where)
        if raw != [hex(number.numerator), hex(number.denominator)]:
            issues.append("W_RECORD_CONTRACT_CONTRADICTION")      # V._encoded is the only writer
        return number

    def bounds(raw, where):
        need(type(raw) is list and len(raw) == 2, "enclosure shape differs: " + where)
        return exact(raw[0], where), exact(raw[1], where)

    identity = value.get("measure_id")
    summary = {"known_method": value.get("method") == WALL_METHOD, "issues": issues, "record": digest(value),
               "inputs": digest({key: value.get(key) for key in WALL_INPUTS}),
               "faces": digest(value.get("faces")), "rows": {}, "cells": {},
               "self_identity": type(identity) is str and
               identity == digest({k: v for k, v in value.items() if k != "measure_id"})}
    # The producer's own reader (WallMeasures.restore) and writer (_measure_walls): value types, required
    # keys, body identity, chronological history, the derived support ids and the stored refinement inputs.
    if not summary["self_identity"]:
        issues.append("W_MEASURE_ID_CONTRADICTION")
    leaves = value.get("max_leaves")
    if not _restorable(value) or any(key not in value for key in WALL_REQUIRED) or \
            type(value.get("rows")) is not list or type(value.get("faces")) is not list or \
            type(value.get("trajectory")) is not dict or type(leaves) is not int or leaves < 1:
        issues.append("W_RECORD_CONTRACT_CONTRADICTION")
    trajectory = value.get("trajectory")
    segments = trajectory.get("segments") if type(trajectory) is dict else None
    history_ok = (type(segments) is list and bool(segments) and digest(segments) == value.get("trajectory_id")
                  and digest(segments[:-1]) == value.get("prior_trajectory_id"))
    summary["history"] = {"trajectory_id": value.get("trajectory_id") if history_ok else None,
                          "prior_trajectory_id": value.get("prior_trajectory_id") if history_ok else None}
    if not history_ok:
        issues.append("W_HISTORY_IDENTITY_CONTRADICTION")
    if not summary["known_method"]:
        return summary
    # _measure_walls' one writer: exact key set and fixed text; descriptor() adds only measure_id.
    if set(value) != WALL_KEYS or any(value.get(name) != text for name, text in WALL_FIXED.items()):
        issues.append("W_RECORD_CONTRACT_CONTRADICTION")
    stored = {name: exact(value[name], name) for name in ("start_time_s", "end_time_s", "max_volume_error_m3")
              if name in value}
    # _measure_walls refuses end <= start and a negative width.
    if len(stored) < 3 or stored["end_time_s"] <= stored["start_time_s"] or stored["max_volume_error_m3"] < 0:
        issues.append("W_RECORD_CONTRACT_CONTRADICTION")
    support = None
    if history_ok:
        # _measure_walls.support_id: funding, grid, endpoint time and the trajectory prefix at that time.
        base = {"funding_id": value.get("funding_id"), "grid_cell_ids": value.get("grid_cell_ids")}
        support = (digest(dict(base, time_s=value.get("start_time_s"), trajectory_prefix=segments[:-1])),
                   digest(dict(base, time_s=value.get("end_time_s"), trajectory_prefix=segments)))
        if (value.get("start_support_id"), value.get("end_support_id")) != support:
            issues.append("W_RECORD_CONTRACT_CONTRADICTION")
    rows, cells, faces = value.get("rows"), value.get("exterior_cells"), value.get("faces")
    need(type(rows) is list and type(cells) is list and type(faces) is list,
         "W record rows/exterior_cells/faces missing")
    totals = {}
    for face in faces:
        need(type(face) is dict, "W face malformed")
        if set(face) != WALL_FACE_KEYS or type(face.get("normal_has_constant_sign")) is not bool:
            issues.append("W_RECORD_CONTRACT_CONTRADICTION")
            continue
        key = digest([face.get("side"), face.get("face_index"), face.get("cell_id")])
        need(key not in totals, "duplicate W face")
        totals[key] = [exact(face[sign[3]], sign[3]) for sign in ROW_SIGNS]
    sums = {key: [Fraction(0), Fraction(0)] for key in totals}
    # Per exterior cell: inward lo/hi, outward lo/hi, inward/outward chosen, summed deviations.
    per_cell = {}
    for row in rows:
        need(type(row) is dict, "W row malformed")
        if set(row) != WALL_ROW_KEYS:
            issues.append("W_RECORD_CONTRACT_CONTRADICTION")
            continue
        face = digest([row.get("side"), row.get("face_index"), row.get("cell_id")])
        key = digest([row.get("side"), row.get("face_index"), row.get("cell_id"), row.get("exterior_cell_key")])
        need(key not in summary["rows"], "duplicate W row key")
        entry = []
        for value_name, bounds_name, deviation_name, _ in ROW_SIGNS:
            lo, hi = bounds(row[bounds_name], bounds_name)
            chosen, deviation = exact(row[value_name], value_name), exact(row[deviation_name], deviation_name)
            # integration_collar_geometry._partition: 0 <= lo <= v <= hi; deviation by definition.
            if not 0 <= lo <= chosen <= hi or deviation != max(chosen-lo, hi-chosen):
                issues.append("W_ROW_CONTRACT_CONTRADICTION")
            entry.append((lo, hi, chosen, deviation))
        if face in sums:
            for index in range(2):
                sums[face][index] += entry[index][2]
        else:
            issues.append("W_FACE_CLOSURE_CONTRADICTION")
        (in_lo, in_hi, in_v, in_dev), (out_lo, out_hi, out_v, out_dev) = entry
        accumulated = per_cell.setdefault(digest(row.get("exterior_cell_key")), [Fraction(0)]*7)
        for index, amount in enumerate((in_lo, in_hi, out_lo, out_hi, in_v, out_v, in_dev+out_dev)):
            accumulated[index] += amount
        summary["rows"][key] = tuple(entry)
    if any(sums[key] != totals[key] for key in totals):
        issues.append("W_FACE_CLOSURE_CONTRADICTION")
    for cell in cells:
        need(type(cell) is dict, "W exterior cell malformed")
        if set(cell) != WALL_CELL_KEYS:
            issues.append("W_RECORD_CONTRACT_CONTRADICTION")
            continue
        key = digest(cell.get("exterior_cell_key"))
        need(key not in summary["cells"], "duplicate W exterior cell key")
        entry = {name: bounds(cell[name], name) for name in CELL_ENCLOSURES}
        admissible = bounds(cell["chosen_change_admissible_bounds_m3"], "chosen_change_admissible_bounds_m3")
        chosen = exact(cell["chosen_volume_change_m3"], "chosen_volume_change_m3")
        error = exact(cell["chosen_volume_change_error_m3"], "chosen_volume_change_error_m3")
        if support and (cell.get("start_support_id"), cell.get("end_support_id")) != tuple(
                digest({"key": cell.get("exterior_cell_key"), "support_id": side}) for side in support):
            issues.append("W_RECORD_CONTRACT_CONTRADICTION")
        in_lo, in_hi, out_lo, out_hi, in_v, out_v, deviation = per_cell.pop(key, [Fraction(0)]*7)
        geometry = entry["geometry_volume_change_bounds_m3"]
        flux, common = entry["flux_volume_change_bounds_m3"], entry["gcl_intersection_bounds_m3"]
        # Exact assembly of the source endpoint loop: flux from the face totals, GCL intersection,
        # chosen change from the allocations and its derived admissible allowance.
        if (any(lo > hi for lo, hi in entry.values()) or flux != (out_lo-in_hi, out_hi-in_lo) or
                chosen != out_v-in_v or error != deviation or
                common != (max(geometry[0], flux[0]), min(geometry[1], flux[1])) or
                admissible != (common[0]-error, common[1]+error) or not admissible[0] <= chosen <= admissible[1]):
            issues.append("W_CELL_CONTRACT_CONTRADICTION")
        entry.update(chosen_change_admissible_bounds_m3=admissible, chosen_volume_change_m3=(chosen, chosen),
                     chosen_volume_change_error_m3=(error, error))
        summary["cells"][key] = entry
    if per_cell:
        issues.append("W_CELL_CONTRACT_CONTRADICTION")   # rows for an exterior cell the record does not list
    return summary


def compare_enclosures(old, new):
    """('equal'|'changed'|'disjoint') for two certified enclosures of the same quantity."""
    if old == new:
        return "equal"
    return "disjoint" if max(old[0], new[0]) > min(old[1], new[1]) else "changed"


class Context:
    """Verified-boundary inputs only. Raw record identity is checked again here.

    manifests/source_pins are from authenticated arm source inventories.
    source_bytes contains exactly source_paths(inventory), with exact selected bytes.
    records[arm][kind] = {'identity': independent reader target SHA, 'raw': bytes}.
    reader_pairs is the existing independently re-derived cross-arm SHA pairing.
    No observation sidecar, contract assertions or purported proof file is accepted.
    """
    def __init__(self, manifests, source_pins, source_bytes, records, reader_pairs):
        for value in (manifests, source_pins, source_bytes, records):
            need(isinstance(value, Mapping) and set(value) == {"before", "after"}, "complete arm pair required")
        need(all(type(pin) is str and SHA.fullmatch(pin) for pin in manifests.values()),
             "invalid authenticated source manifest identity")
        self.manifests = dict(manifests)
        self.catalogs = {arm: compile_catalog(source_pins[arm], source_bytes[arm]) for arm in manifests}
        self.source_pins = {arm: {path: source_pins[arm][path] for path in source_paths(source_pins[arm])}
                            for arm in manifests}
        self.assigned, self.unreviewed = {}, {}
        for arm, catalog in self.catalogs.items():
            self.assigned[arm], self.unreviewed[arm] = classify(catalog)
        self.records, self.walls = {}, {}
        for arm, mapping in records.items():
            need(isinstance(mapping, Mapping), "reader records must be a mapping")
            self.records[arm], self.walls[arm] = {}, {}
            for kind, item in mapping.items():
                need(type(kind) is str and kind and type(item) is dict and
                     set(item) == {"identity", "raw"}, "reader record binding malformed")
                pin, raw = item["identity"], item["raw"]
                need(type(pin) is str and SHA.fullmatch(pin) and type(raw) is bytes and
                     sha256(raw).hexdigest() == pin, "dump record differs from independent reader target")
                # Keep only compact source-field references, not raw bytes or
                # large cell/face/trajectory records. Lazy Mapping is supported.
                record = decoded(raw)
                summary = {"identity": pin, "is_exterior": False}
                if type(record) is dict and record.get("schema") == MESH and \
                        record.get("physical_geometry_family") != DIFFERENTIAL:
                    fields = {}
                    for field, count in (("representative_quaternion", 4), ("pose_operator_error_bound", 1)):
                        if field in record:
                            values = record[field] if count == 4 else [record[field]]
                            need(type(values) is list and len(values) == count,
                                 "source-defined quantity shape differs: " + field)
                            for value in values:
                                rational(value, field)
                            fields[field] = digest(record[field])
                    history, segments = record.get("trajectory_id"), record.get("trajectory_segments")
                    history_ok = type(history) is str and bool(SHA.fullmatch(history)) and type(segments) is list
                    summary.update(is_exterior=True, fields=fields,
                                   history={"trajectory_id": history if history_ok else None,
                                            "segments_sha256": digest(segments) if history_ok else None},
                                   inputs=digest({key: record.get(key) for key in E_INPUTS})
                                   if all(key in record for key in E_INPUTS) else None)
                self.records[arm][kind] = summary
                walls = [(path, wall_summary(value)) for path, value in wall_records(record)]
                if walls:
                    self.walls[arm][kind] = walls
                del raw, record
        self.reader_pairs = set()
        for pair in reader_pairs:
            need(type(pair) in (list, tuple) and len(pair) == 2 and
                 all(type(pin) is str and SHA.fullmatch(pin) for pin in pair),
                 "independent reader identity pair malformed")
            self.reader_pairs.add(tuple(pair))
        self.slots = [slot for slot, row in SLOTS.items() if any(
            self.assigned[arm][slot] if row["sites"] else
            any(item["family"] == row["family"] for item in self.unreviewed[arm] + self.catalogs[arm]["unresolved"])
            for arm in self.catalogs)]
        self.wall_findings = self._compare_walls()

    def paired(self, kind):
        a, b = self.records["before"].get(kind), self.records["after"].get(kind)
        return bool(a and b and (a["identity"], b["identity"]) in self.reader_pairs)

    def source_pair(self, family):
        a, b = (self.catalogs[arm]["producers"].get(family) for arm in ("before", "after"))
        return (a["sha256"] if a else None, b["sha256"] if b else None)

    def dependency_changes(self, family):
        """Modules of the producer's package import closure (either arm) whose bytes differ across arms
        other than by a reviewed width transform; the producer's own pair is judged separately."""
        paths = set()
        for arm in ("before", "after"):
            paths.update(self.catalogs[arm]["dependencies"].get(family, ()))
        changed = []
        for path in sorted(paths):
            pins = tuple(self.source_pins[arm].get(path) for arm in ("before", "after"))
            if pins[0] != pins[1] and (path, *pins) not in TRANSFORMS:
                changed.append(path)
        return changed

    def _compare_walls(self):
        """Per W-internal slot: joined outputs, FAIL/REVIEW issues and change counts."""
        findings = {slot: {"outputs": [], "issues": [], "changed": 0, "equal": 0}
                    for slot, row in SLOTS.items() if row["join"] == "wall"}
        every = tuple(findings)

        def note(slots, issue):
            for slot in slots:
                findings[slot]["issues"].append(issue)

        def count(slots, same):
            for slot in slots:
                findings[slot]["equal" if same else "changed"] += 1

        identical_code = self.manifests["before"] == self.manifests["after"]
        zero = ((Fraction(0),)*4,)*2     # the source omits exactly the all-zero rows
        for kind in sorted(set(self.walls["before"]) | set(self.walls["after"])):
            old, new = dict(self.walls["before"].get(kind, ())), dict(self.walls["after"].get(kind, ()))
            for path in sorted(set(old) | set(new)):
                where = kind + ":" + "/".join(path)
                a, b = old.get(path), new.get(path)
                for summary in (a, b):
                    for issue in summary["issues"] if summary else ():
                        note(every, where + ":" + issue)
                if not (a and b and self.paired(kind)):
                    note(every, where + ":W_RECORD_CORRESPONDENCE_MISSING")
                    continue
                for slot in every:
                    findings[slot]["outputs"].append({
                        "record_kind": kind, "path": list(path),
                        "before_record_identity": self.records["before"][kind]["identity"],
                        "after_record_identity": self.records["after"][kind]["identity"],
                        "history": deepcopy(a["history"])})
                if not (a["known_method"] and b["known_method"]):
                    note(every, where + ":W_UNREVIEWED_METHOD")
                    continue
                if a["inputs"] != b["inputs"] or a["history"] != b["history"]:
                    note(every, where + ":W_INVOCATION_INPUTS_DIFFER")
                    continue
                if identical_code and a["record"] != b["record"]:
                    # Identical code and stored inputs reproduce the whole record (extra cells included).
                    note(every, where + ":W_IDENTICAL_CODE_OUTPUT_CHANGED")
                if a["faces"] != b["faces"]:
                    note(every, where + ":W_POSE_INDEPENDENT_FACES_CHANGED")
                for key in sorted(set(a["rows"]) | set(b["rows"])):
                    for x, y in zip(a["rows"].get(key, zero), b["rows"].get(key, zero), strict=True):
                        state = compare_enclosures(x[:2], y[:2])
                        if state == "disjoint":
                            note(("W.wall-normal",), where + ":W_FLUX_ENCLOSURES_DISJOINT")
                        count(("W.wall-normal",), state == "equal" and x[2:] == y[2:])
                if set(a["cells"]) != set(b["cells"]):
                    note(every, where + ":W_EXTERIOR_CELL_KEYS_DIFFER")
                for key in sorted(set(a["cells"]) & set(b["cells"])):
                    x, y = a["cells"][key], b["cells"][key]
                    for name, (slots, disjoint) in CELL_ENCLOSURES.items():
                        state = compare_enclosures(x[name], y[name])
                        if state == "disjoint":
                            note(slots, where + ":" + disjoint)
                        count(slots, state == "equal")
                    for name, slots in CELL_DERIVED.items():
                        count(slots, x[name] == y[name])
        for item in findings.values():
            if item["changed"]:
                # Identical code and inputs must reproduce exact outputs; otherwise no magnitude bound exists.
                item["issues"].append(("W_IDENTICAL_CODE_OUTPUT_CHANGED" if identical_code else
                                       "W_ENCLOSURE_CHANGED_NO_PROPAGATED_BOUND") + ":%d" % item["changed"])
        return findings


def verdict_of(issues):
    if {code_of(issue) for issue in issues} & FAIL_CODES:
        return "FAIL"
    return "REVIEW" if issues else "BOUND"


def emit_receipt(slot_id, context):
    """Emit complete joined bindings and explicit missing ones; never self-certify."""
    need(isinstance(context, Context), "verified-boundary Context required")
    need(slot_id in context.slots, "slot is not mandatory for these selected sources")
    slot = SLOTS[slot_id]
    family = slot["family"]
    own_module = PRODUCERS[family][0] + ".py"
    arms, issues = {}, []
    for arm in ("before", "after"):
        catalog = context.catalogs[arm]
        producer = catalog["producers"].get(family)
        if producer is None:
            issues.append(arm + ":SELECTED_PRODUCER_ABSENT")
        elif not producer["known"]:
            issues.append(arm + ":UNREVIEWED_SELECTED_PRODUCER")
        accesses = []
        if slot["sites"]:
            sites = context.assigned[arm][slot_id]
            for module, caller, count in slot["sites"]:
                found = sum(1 for site in sites if site["module"] == module and site["caller"] == caller)
                # The slot is selected across both arms: a missing caller module is not inapplicability.
                if found != count:
                    issues.append("%s:%s:%s:REVIEWED_CALL_SITE_ABSENT" % (arm, module, caller))
        else:
            sites = [site for site in context.unreviewed[arm] if site["family"] == family]
            accesses = [row for row in catalog["unresolved"] if row["family"] == family]
            issues.extend("%s:%s:%s:UNREVIEWED_CALL_SITE" % (arm, site["module"], site["caller"]) for site in sites)
            issues.extend("%s:%s:L%d:%s" % (arm, row["module"], row["line"], row["code"]) for row in accesses)
        # Routes: other modules' calls of producer-module functions that reach this slot's own sites.
        own_callers = {caller.split(".")[0] for module, caller, _ in slot["sites"] if module == own_module}
        routes = [row for row in catalog["routes"] if row["family"] == family and own_callers & set(row["reaches"])]
        arms[arm] = {"producer": deepcopy(producer), "call_sites": deepcopy(sites),
                     "unresolved_accesses": deepcopy(accesses), "consequence_routes": deepcopy(routes),
                     "dependency_modules": len(catalog["dependencies"].get(family, ())),
                     "caller_modules": sorted({(site["module"], site["sha256"]) for site in sites
                                               if site["module"] != own_module})}
        arms[arm]["caller_modules"] = [list(row) for row in arms[arm]["caller_modules"]]
    pair = context.source_pair(family)
    relation = None
    if all(arms[arm]["producer"] and arms[arm]["producer"]["known"] for arm in arms):
        relation = "identity" if pair[0] == pair[1] else "n9-rounding" if pair == ROUNDED_PAIRS[family] else None
        if relation is None:
            issues.append("SOURCE_PAIR_NOT_PROVED")
        else:
            # The producer's behaviour also rests on its package import closure.
            changed = context.dependency_changes(family)
            if changed:
                issues.extend(path + ":PRODUCER_DEPENDENCY_SOURCE_CHANGED" for path in changed)
                relation = None
    if relation == "n9-rounding":
        # Rounded pose values these routes carry reach no joined record and no propagated bound.
        issues.extend("%s:%s:%s->%s:POSE_CONSEQUENCE_ROUTE_UNBOUND" % (arm, row["module"], row["caller"], row["member"])
                      for arm in arms for row in arms[arm]["consequence_routes"])
    if slot["sites"] and arms["before"]["caller_modules"] != arms["after"]["caller_modules"]:
        issues.append("CALLER_SOURCE_CHANGED")
    binding = {"invocation_route": PRODUCERS[family][1] + " <- " +
               "|".join("%s:%s" % (module, caller) for module, caller, _ in slot["sites"]),
               "relation": relation, "caller_units": slot["units"],
               "projection": "source exact rational encoding; no binary64",
               "persisted_outputs": list(slot["persisted"]), "consequence": slot["consequence"]}
    correspondence, outputs = [], []
    applicable_radius = None
    comparison_bound = {"kind": "identity"} if relation == "identity" else {"kind": "unbound"}
    if slot["join"] == "mesh":
        binding["refinement_level"] = "not a producer parameter: goal = min(1/2, 3*width/(32*nplanes*R^3))"
        old = {k: v for k, v in context.records["before"].items() if v["is_exterior"]}
        new = {k: v for k, v in context.records["after"].items() if v["is_exterior"]}
        field = slot["output_field"]
        for kind in sorted(set(old) | set(new)):
            a, b = old.get(kind), new.get(kind)
            for arm, item in (("before", a), ("after", b)):
                if item is None:
                    continue
                if field not in item["fields"]:
                    issues.append(arm + ":" + kind + ":MANDATORY_OUTPUT_FIELD_MISSING")
                # A present history that contradicts its own segments fails even when other inputs are missing.
                if item["history"]["trajectory_id"] is not None and \
                        item["history"]["segments_sha256"] != item["history"]["trajectory_id"]:
                    issues.append(arm + ":" + kind + ":E_HISTORY_IDENTITY_CONTRADICTION")
                elif item["history"]["trajectory_id"] is None or item["inputs"] is None:
                    issues.append(arm + ":" + kind + ":SOURCE_HISTORY_CONTEXT_MISSING")
                outputs.append({"arm": arm, "record_kind": kind, "record_identity": item["identity"],
                                "schema": MESH, "path": [kind, field], "value_sha256": item["fields"].get(field),
                                "history": deepcopy(item["history"]), "inputs_sha256": item["inputs"]})
            if not (a and b and context.paired(kind)):
                issues.append(kind + ":INDEPENDENT_RECORD_CORRESPONDENCE_MISSING")
                continue
            if a["inputs"] != b["inputs"]:
                issues.append(kind + ":E_INVOCATION_INPUTS_DIFFER")
                continue
            correspondence.append({
                "record_kind": kind, "before_record_identity": a["identity"],
                "after_record_identity": b["identity"],
                "before_quantity_identity": a["identity"] + "/" + field,
                "after_quantity_identity": b["identity"] + "/" + field,
                "scope": "reader-proved record pair; identical stored invocation inputs and history"})
        if not old and not new and relation != "identity":
            issues.append("NO_READER_BOUND_E_OUTPUT")
        rounded = relation == "n9-rounding"
        if relation is None:
            pass
        elif slot_id == "E.representative-quaternion":
            # The operator error never becomes the quaternion's own radius: stored/4 only scales the
            # cross-arm difference that the named proof certifies.
            comparison_bound = {"kind": "pose-quaternion", "proof": E_QUAT_PROOF, "norm": "l2",
                                "scale": {"path": ["pose_operator_error_bound"], "factor": "1/4"},
                                "rule": "|q_after-q_before|_2 < 2**-11*min(e_before,e_after)"} if rounded else \
                {"kind": "exact"}
        else:
            comparison_bound = {"kind": "radius-growth", "shift": 11, "proof": E_RADIUS_PROOF,
                                "rule": "before <= after and after-before < 2**-11*before"} if rounded else \
                {"kind": "exact"}
    elif slot["join"] == "wall":
        binding["refinement_level"] = ("adaptive internal subdivision level; persisted enclosures are "
                                       "level-independent certified bounds")
        found = context.wall_findings[slot_id]
        outputs = deepcopy(found["outputs"])
        issues.extend(found["issues"])
        if not outputs and relation != "identity":
            issues.append("NO_READER_BOUND_W_OUTPUT")
        comparison_bound = {"kind": "enclosure-intersection",
                            "rule": "same face/cell/interval/history enclosures intersect; identical code is exact",
                            "magnitude": "no propagated bound: a changed enclosure is REVIEW"} \
            if slot["persisted"] else {"kind": "refusal-only", "rule": "zero refusal flips (stage outcome)"}
        binding["changed_outputs"], binding["equal_outputs"] = found["changed"], found["equal"]
    elif slot["sites"]:
        binding["refinement_level"] = "caller-supplied level (or the E goal); not persisted"
        if relation == "n9-rounding":
            issues.append("POSE_CONSUMER_NO_PROPAGATED_BOUND")
            comparison_bound = {"kind": "no-propagated-bound", "rule": NO_BOUND}
    else:
        binding["refinement_level"] = "unknown"
        comparison_bound = {"kind": "unreviewed"}
    issues = sorted(set(issues))
    return {
        "schema": RECEIPT_SCHEMA, "slot": slot_id, "mandatory": True,
        "composition": deepcopy(context.manifests),
        "quantity": {key: deepcopy(slot[key]) for key in QUANTITY_KEYS},
        "arms": arms, "binding": binding, "outputs": outputs, "correspondence": correspondence,
        "applicable_radius": applicable_radius, "comparison_bound": comparison_bound,
        "verdict": verdict_of(issues), "issues": issues,
        "authority": "provenance only; numerical rows judge values; no guard release",
    }


def validate_receipt(receipt, context):
    """Re-derive every byte-independent field from verified inputs, never from receipt assertions."""
    if type(receipt) is not dict or type(receipt.get("slot")) is not str:
        return {"verdict": "FAIL", "code": "MALFORMED_PRODUCER_RECEIPT"}
    try:
        expected = emit_receipt(receipt["slot"], context)
    except (ProvenanceError, RecursionError, MemoryError) as error:
        return {"verdict": "FAIL", "code": "UNBOUND_PRODUCER_RECEIPT", "reason": str(error)}
    try:
        supplied = digest(receipt)
    except (TypeError, ValueError, RecursionError, MemoryError):
        return {"verdict": "FAIL", "code": "MALFORMED_PRODUCER_RECEIPT"}
    # Canonical bytes, not Python equality: True/1/1.0 and other JSON-distinct values must not pass.
    if supplied != digest(expected):
        return {"verdict": "FAIL", "code": "PRODUCER_RECEIPT_CONTRADICTS_INDEPENDENT_INPUTS"}
    return {"verdict": expected["verdict"], "code": "PRODUCER_RECEIPT_RECOMPUTED",
            "receipt_sha256": supplied, "issues": expected["issues"]}


def assess_records(manifests, source_pins, source_bytes, records, reader_pairs):
    """Comparator entry point: mandatory results even for byte-equal dumped records."""
    try:
        context = Context(manifests, source_pins, source_bytes, records, reader_pairs)
        receipts = [emit_receipt(slot, context) for slot in context.slots]
        verdicts = {row["verdict"] for row in receipts}
        verdict = ("NOT_APPLICABLE" if not receipts else "FAIL" if "FAIL" in verdicts else
                   "REVIEW" if "REVIEW" in verdicts else "BOUND")
        return {
            "schema": SCHEMA, "verdict": verdict,
            "scope": "every W._pose_vector/E._representative_pose call site, consequence route and producer "
                     "import closure in the selected package inventory (canonical relative keys; test/fixture "
                     "paths excluded; profile helpers outside; computed names unscannable); no "
                     "Pressure/Geometry/Heat contract",
            "mandatory_slots": context.slots,
            "receipts": receipts, "receipt_sha256": [digest(row) for row in receipts],
            "issues": [row["slot"] + ":" + issue for row in receipts for issue in row["issues"]],
            "remaining_dependency": "Differential-route (D/P) pose consumers, W consequence routes past the "
                                    "joined records (E builder endpoint volumes, spatial ALE), W "
                                    "enclosure-change magnitudes, downstream mesh metrics and Heat need their "
                                    "own propagated bound or independent verification.",
        }
    except (ProvenanceError, SyntaxError, TypeError, ValueError, KeyError, IndexError, AttributeError,
            RecursionError, MemoryError) as error:
        # Too-deep records or sources (RecursionError, MemoryError) cannot be checked, so they fail too.
        return {"schema": SCHEMA, "verdict": "FAIL", "code": "PROVENANCE_INPUT_INTEGRITY",
                "reason": str(error), "issues": [str(error)],
                "mandatory_slots": [], "receipts": [], "receipt_sha256": []}
