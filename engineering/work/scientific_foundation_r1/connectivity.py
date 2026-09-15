"""Barrier-respecting seasonal reachability at explicit raster support.

Distances are shortest 8-neighbour path lengths, not Euclidean distances across
barriers, movement probabilities, or proof of sub-grid passability. Diagonal
corner cutting is forbidden. This bounded reference leaves resistance models
and species-specific acceptance to a later justified choice.
"""
from __future__ import annotations

import ast
import hashlib
import heapq
import math
from pathlib import Path
import types
import numpy as np
from .erosion import real

MAX_CELLS = 65536
HISTORICAL = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted/work/species_habitat")
HS17_PATH = HISTORICAL / "frosthirsch_hs17/build_hs17_frosthirsch.py"
HS17_SHA256 = "ff3ecd6c1724de7cb1cdb476bd410347b41a336d2d7409289e3a131f950e3347"
FRAMEWORK_PATH = HISTORICAL / "framework/habitat_atlas_framework.py"
FRAMEWORK_SHA256 = "2c6bebdbf17a8d39dfd55cae0d07d77a772206033c2e6f48df79021e48fb7521"


def mask(value, name, shape=None):
    value = np.asarray(value)
    if value.dtype != np.bool_ or value.ndim != 2 or not value.size or value.size > MAX_CELLS:
        raise ValueError(name + " must be a bounded two-dimensional Boolean mask")
    if shape is not None and value.shape != shape:
        raise ValueError(name + " has incompatible grid support")
    return value


def path_distance(seed, passable, *, dx_m, dy_m):
    """Multi-source Dijkstra; no endpoints means infinite/unreachable distance."""
    allowed = mask(passable, "passable")
    sources = mask(seed, "seed", allowed.shape) & allowed
    dx = real(dx_m, "dx_m", positive=True)
    dy = real(dy_m, "dy_m", positive=True)
    diagonal = math.hypot(dx, dy)
    if not math.isfinite(diagonal):
        raise ValueError("grid edge length overflow")
    rows, cols = allowed.shape
    result = np.full(allowed.shape, np.inf, np.float64)
    queue = []
    for row, col in zip(*np.nonzero(sources)):
        result[row, col] = 0.
        queue.append((0., int(row), int(col)))
    heapq.heapify(queue)
    edges = ((-1,0,dy),(1,0,dy),(0,-1,dx),(0,1,dx),(-1,-1,diagonal),(-1,1,diagonal),(1,-1,diagonal),(1,1,diagonal))
    while queue:
        distance, row, col = heapq.heappop(queue)
        if distance != result[row, col]:
            continue
        for dr, dc, length in edges:
            rr, cc = row+dr, col+dc
            if not (0 <= rr < rows and 0 <= cc < cols) or not allowed[rr, cc]:
                continue
            if dr and dc and not (allowed[row, cc] and allowed[rr, col]):
                continue
            candidate = distance + length
            if not math.isfinite(candidate) or candidate <= distance:
                raise ValueError("path length overflow or lost positive edge")
            if candidate < result[rr, cc]:
                result[rr, cc] = candidate
                heapq.heappush(queue, (candidate, rr, cc))
    return result


def seasonal_reachability(summer, winter, passable, *, dx_m, dy_m,
                          max_endpoint_distance_m, max_unsuitable_gap_m):
    """The inherited 'gap' parameter is a NEAREST-ENDPOINT RADIUS.

    It is applied on every traversed cell, not a limit on the total continuous
    unsuitable segment. On a straight line between endpoint patches a radius r
    can admit a gap of length 2r. That distinction must survive downstream use;
    no biological threshold is silently halved or reinterpreted here.
    """
    allowed = mask(passable, "passable")
    summer = mask(summer, "summer", allowed.shape)
    winter = mask(winter, "winter", allowed.shape)
    limit = real(max_endpoint_distance_m, "endpoint distance", positive=True)
    gap = real(max_unsuitable_gap_m, "unsuitable gap", positive=True)
    union = path_distance(summer | winter, allowed, dx_m=dx_m, dy_m=dy_m)
    # All intermediate cells must also respect the declared gap bound. Computing
    # endpoint distances before this cut could connect across excluded terrain.
    corridor = allowed & (union <= gap)
    to_summer = path_distance(summer, corridor, dx_m=dx_m, dy_m=dy_m)
    to_winter = path_distance(winter, corridor, dx_m=dx_m, dy_m=dy_m)
    return {"summer_distance_m": to_summer, "winter_distance_m": to_winter,
            "nearest_endpoint_distance_m": union,
            "reachable_both": corridor & (to_summer <= limit) & (to_winter <= limit),
            "traversable_corridor": corridor, "movement_probability": None,
            "gap_parameter_semantics": "maximum traversable distance to nearest seasonal endpoint; radius, not continuous segment length"}


def _source(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("reviewed ecological source changed: " + path.name)
    return ast.parse(data)


def corrected_hs17_movement(predictors, *, dx_m, dy_m):
    """Execute the actual retained HS17 movement formula with corrected distances.

    The exact reviewed AST block is used; no complete atlas is loaded or written.
    Required predictor/threshold names are unchanged. A local copy of raw family
    dictionaries prevents the component call mutating the caller's input atlas.
    No framework entrypoint, source path mutation or rendering code is executed.
    """
    root = _source(HS17_PATH, HS17_SHA256)
    framework = _source(FRAMEWORK_PATH, FRAMEWORK_SHA256)
    derive = next(x for x in root.body if isinstance(x, ast.FunctionDef) and x.name == "derive")
    # Find the unique contiguous statement block, nested in the family loop.
    blocks = []
    for node in ast.walk(derive):
        if isinstance(node, ast.For):
            for first, statement in enumerate(node.body):
                if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "summer_endpoint" for t in statement.targets):
                    for last in range(first, len(node.body)):
                        candidate = node.body[last]
                        if isinstance(candidate, ast.Assign) and ast.unparse(candidate.targets[0]) == "raw[family]['movement']":
                            blocks.append(node.body[first:last+1])
                            break
    if len(blocks) != 1:
        raise ValueError("reviewed HS17 movement block shape changed")
    block = blocks[0]
    dependencies = {"np": np}
    selected = [x for x in framework.body if isinstance(x, ast.FunctionDef) and x.name in {"ramp", "decline", "gmean"}]
    if len(selected) != 3:
        raise ValueError("reviewed habitat helper inventory changed")
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(FRAMEWORK_PATH), "exec", dont_inherit=True), dependencies)
    haf = types.SimpleNamespace(**{key: dependencies[key] for key in ("ramp", "decline", "gmean")})
    required = {"alpine", "monthly", "atmospheric_moisture", "mean_slope", "movement_p", "ruggedness", "raw", "family", "generic_shelter", "water_margin", "snow_persistence", "trough", "tpi", "relative_position", "surface_stability", "avalanche_track", "land", "volcanic_danger", "snow_p"}
    if not isinstance(predictors, dict) or set(predictors) != required:
        raise ValueError("exact HS17 movement predictor set required")
    namespace = dict(predictors)
    allowed = mask(namespace["land"], "land").copy()
    p = namespace["movement_p"]
    s = namespace["snow_p"]
    endpoint_support = real(p["seasonal_endpoint_support_min"], "seasonal endpoint support threshold")
    if endpoint_support > 1:
        raise ValueError("seasonal endpoint support threshold must lie in [0,1]")
    for field, threshold in (("mean_slope", p["mean_slope_degrees_max"]),
                             ("ruggedness", p["ruggedness_11km_m_max"]),
                             ("avalanche_track", p["avalanche_track_danger_max"]),
                             ("volcanic_danger", s["geothermal_danger_max"])):
        array = np.asarray(namespace[field])
        if array.shape != allowed.shape or not np.isfinite(array).all():
            raise ValueError("invalid movement barrier predictor " + field)
        if np.any(array < 0):
            raise ValueError("negative movement barrier predictor " + field)
        allowed &= array <= real(threshold, field + " threshold")
    for key in required - {"raw", "family", "movement_p", "snow_p", "monthly", "land"}:
        array = np.asarray(namespace[key])
        if array.shape != allowed.shape or not np.isfinite(array).all():
            raise ValueError("incompatible/missing physical support: " + key)
    family = namespace["family"]
    if not isinstance(family, str) or not family:
        raise ValueError("explicit family identity required")
    for label, array in (("monthly snow-free fraction", namespace["monthly"]["snowfree_fraction"]),
                         ("winter browse", namespace["raw"][family]["winter_browse"])):
        value = np.asarray(array)
        if value.shape != allowed.shape or not np.isfinite(value).all():
            raise ValueError("incompatible/missing physical support: " + label)
    namespace["raw"] = {family: dict(namespace["raw"][family])}
    namespace.update(np=np, haf=haf, safe01=lambda x: np.nan_to_num(np.clip(x, 0., 1.), nan=0.).astype(np.float32))
    # Replace the three source distance assignments together, after both endpoint
    # masks exist, with a single common barrier/gap-aware connectivity result.
    changed = []
    replacements = 0
    for statement in block:
        if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
            name = statement.targets[0].id
            if name == "summer_distance":
                changed.extend(ast.parse("_reach = _connect(summer_seed, winter_seed)\nsummer_distance = _reach['summer_distance_m'] / 1000.\nwinter_distance = _reach['winter_distance_m'] / 1000.\nsuitable_endpoint_distance = _reach['nearest_endpoint_distance_m'] / 1000.").body)
                replacements += 1
                continue
            if name in {"winter_distance", "suitable_endpoint_distance"}:
                replacements += 1
                continue
        changed.append(statement)
    if replacements != 3:
        raise ValueError("reviewed endpoint distance assignments changed")
    namespace["_connect"] = lambda summer, winter: seasonal_reachability(
        summer, winter, allowed, dx_m=dx_m, dy_m=dy_m,
        max_endpoint_distance_m=1000*real(p["summer_winter_endpoint_distance_km_max"], "endpoint range", positive=True),
        max_unsuitable_gap_m=1000*real(p["dry_or_unsuitable_gap_km_max"], "gap range", positive=True))
    exec(compile(ast.fix_missing_locations(ast.Module(body=changed, type_ignores=[])), str(Path(__file__)), "exec", dont_inherit=True), namespace)
    return {"movement_support": namespace["raw"][family]["movement"], **namespace["_reach"],
            "predecessor_sha256": HS17_SHA256, "framework_sha256": FRAMEWORK_SHA256,
            "interpretation": "relative HS17 support with raster-scale reachable seasonal endpoints; not occupancy probability"}
