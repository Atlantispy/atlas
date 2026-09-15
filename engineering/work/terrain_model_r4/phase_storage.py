"""R4 positive-depth-connected phase storage; no time integration or bed edits.

R2 geometry is loaded from hash-pinned source bytes, without importing a mutable
module by name. All phase inputs are cell inventories, not rates. See methods.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import threading
import types

MAX_CELLS = 4096
MAX_TRANSFERS = 262144
VOLUME_ATOL = 1e-9
RTOL = 1e-12
_BASE = Path(__file__).resolve().parent
SOURCE_PINS = {
    "basin_topology.py": "0584205e94552edae942136d26cace5e3a5678b32151be95ec7aaa348e4807e2",
    "water.py": "ee222afab626f9ecf4233bd4cdb6048aa2041d7ae3762c9c4c8843c8cc3a362c",
}
DESIGN_SHA256 = "8e569a1083cf8f7bef3e0f88496fdd0ea413df2453ce558b28fbf527b40f7914"
R3_PHASE_SHA256 = "38bc38075e0a7a52209891ab7250db3cf4128b17a67ff509675feb62121055b7"
R3_RELEASE_SHA256 = "d60511fef613e0d72e36cc930a7bf98dfd9791bfec3f807c2c2f32b7dc8916df"
_SOURCE_CACHE_LOCK = threading.RLock()
_SOURCE_CACHE_ENABLED = True
_SOURCE_CACHE = None
_SOURCE_CACHE_HITS = 0
_SOURCE_CACHE_MISSES = 0


class UnsupportedPhaseRouting(ValueError):
    """A requested transition lacks a represented positive-depth closure."""

    def __init__(self, message, **context):
        super().__init__(message)
        self.context = context


def _number(value, label, *, positive=False, nonnegative=False):
    if type(value) not in (int, float):
        raise ValueError(label + " requires a finite number, not Boolean")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(label + " exceeds binary64") from exc
    if not math.isfinite(value) or positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(label + " outside supported finite range")
    return value


def _sum(values):
    try:
        return _number(math.fsum(values), "derived sum")
    except OverflowError as exc:
        raise ValueError("derived sum overflow") from exc


def _float(value):
    try:
        result = _number(float(value), "exact volume converted to binary64", nonnegative=True)
        if value > 0 and result == 0:
            raise ValueError("positive exact volume underflows binary64")
        return result
    except OverflowError as exc:
        raise ValueError("derived volume exceeds binary64") from exc


def _check(residual, *scale):
    residual = _number(residual, "residual")
    if abs(residual) > VOLUME_ATOL + RTOL * max([0.] + [abs(v) for v in scale]):
        raise ValueError("phase/geometry conservation exceeds declared tolerance")
    return residual


def _list(values, label, *, positive=False, nonnegative=False):
    if type(values) is not list or not 1 <= len(values) <= MAX_CELLS:
        raise ValueError(label + " requires 1..4096 plain-list entries")
    return [_number(v, label, positive=positive, nonnegative=nonnegative) for v in values]


def configure_source_cache(*, enabled=True, reset=False):
    """Engineering control only; never changes source verification or results."""
    if type(enabled) is not bool or type(reset) is not bool:
        raise ValueError("source-cache controls require Boolean values")
    global _SOURCE_CACHE_ENABLED, _SOURCE_CACHE, _SOURCE_CACHE_HITS, _SOURCE_CACHE_MISSES
    with _SOURCE_CACHE_LOCK:
        _SOURCE_CACHE_ENABLED = enabled
        if reset or not enabled:
            _SOURCE_CACHE = None
        if reset:
            _SOURCE_CACHE_HITS = _SOURCE_CACHE_MISSES = 0


def source_cache_info():
    """Separate diagnostic counters, deliberately absent from scientific JSON."""
    with _SOURCE_CACHE_LOCK:
        return {"enabled": _SOURCE_CACHE_ENABLED, "hits": _SOURCE_CACHE_HITS,
                "misses": _SOURCE_CACHE_MISSES,
                "entries": int(_SOURCE_CACHE is not None)}


def _binding_signature(value):
    """Detect private-global rebinding/mutation; not a hostile-code sandbox."""
    if type(value) in (str, int, float, bool, bytes, type(None)):
        return (type(value), value)
    if type(value) is tuple:
        return (tuple, tuple(_binding_signature(v) for v in value))
    if type(value) is dict:
        return (dict, tuple(sorted((k, _binding_signature(v)) for k, v in value.items())))
    if isinstance(value, types.FunctionType):
        return (types.FunctionType, id(value), id(value.__code__),
                _binding_signature(value.__defaults__),
                _binding_signature(value.__kwdefaults__),
                _binding_signature(value.__annotations__),
                _binding_signature(value.__dict__))
    if isinstance(value, type) and value.__module__.startswith("_r4_bound_"):
        return (type, id(value), tuple(sorted(
            (k, _binding_signature(v)) for k, v in vars(value).items())))
    # These pinned modules import only stdlib modules/types and immutable
    # __future__ metadata; mutable scientific state lives inside functions.
    if isinstance(value, (list, set, bytearray)):
        raise ValueError("mutable private source global cannot be cached")
    return (type(value), id(value))


def _module_signature(module):
    # Standard-runtime imports/builtins are shared in uncached execution too;
    # detect replacement here without claiming to sandbox global Python state.
    return tuple(sorted((key, (type(value), id(value)) if key == "__builtins__"
                         else _binding_signature(value))
                        for key, value in vars(module).items()))


def _check_cached_globals():
    # Caller holds the lock. Source code is also rehashed separately: this
    # catches accidental in-process changes that a disk hash cannot reveal.
    if _SOURCE_CACHE is not None:
        for name, module in _SOURCE_CACHE[1].items():
            if _module_signature(module) != _SOURCE_CACHE[2][name]:
                raise ValueError("cached private source globals changed: " + name)


def _bound_sources():
    records, source_bytes = {}, {}
    for name, expected in SOURCE_PINS.items():
        path = _BASE.parent / "terrain_model_r2" / name
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected:
            raise ValueError("frozen R2 source identity mismatch: " + name)
        records[name] = {"path": str(path), "sha256": digest, "size_bytes": len(data)}
        source_bytes[name] = data
    design = _BASE.parent / "terrain_model_r3" / "CAPTURE_DESIGN.md"
    data = design.read_bytes()
    if hashlib.sha256(data).hexdigest() != DESIGN_SHA256:
        raise ValueError("frozen capture design identity mismatch")
    records["CAPTURE_DESIGN.md"] = {
        "path": str(design), "sha256": DESIGN_SHA256, "size_bytes": len(data)}
    source_bytes["CAPTURE_DESIGN.md"] = data
    predecessor = _BASE.parent / "terrain_model_r3" / "phase_storage.py"
    release = _BASE.parent.parent / "outputs" / "terrain-model-r3" / "release-r3-01" / "REFERENCE_VERIFICATION.json"
    for key, path, expected in (("R3/phase_storage.py", predecessor, R3_PHASE_SHA256),
                                ("R3/REFERENCE_VERIFICATION.json", release, R3_RELEASE_SHA256)):
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("frozen predecessor identity mismatch: " + key)
        records[key] = {"path": str(path), "sha256": expected, "size_bytes": len(data)}
        source_bytes[key] = data
    # Read exact indexed roles rather than treating a successful old report as
    # new physical authority. Full unrelated R3/R2 output rehash is root-owned.
    receipt = json.loads(data)
    source_rows = {row["name"]: row for row in receipt["import_loaded_source_pins"]}
    for role, expected in (("phase_storage.py", R3_PHASE_SHA256),
                           ("CAPTURE_DESIGN.md", DESIGN_SHA256),
                           ("R2/basin_topology.py", SOURCE_PINS["basin_topology.py"]),
                           ("R2/water.py", SOURCE_PINS["water.py"])):
        if source_rows[role]["sha256"] != expected:
            raise ValueError("predecessor role binding mismatch")
    # Every call reads/verifies the complete closure before consulting cache.
    # One bounded entry holds only compiled modules, never fields or results.
    key = tuple((name, records[name]["path"], records[name]["sha256"],
                 source_bytes[name]) for name in records)
    global _SOURCE_CACHE, _SOURCE_CACHE_HITS, _SOURCE_CACHE_MISSES
    with _SOURCE_CACHE_LOCK:
        _check_cached_globals()
        if _SOURCE_CACHE_ENABLED and _SOURCE_CACHE is not None and _SOURCE_CACHE[0] == key:
            _SOURCE_CACHE_HITS += 1
            return dict(_SOURCE_CACHE[1]), records
        _SOURCE_CACHE_MISSES += 1
        modules = {}
        for name in SOURCE_PINS:
            module = types.ModuleType("_r4_bound_" + Path(name).stem)
            module.__file__ = records[name]["path"]
            exec(compile(source_bytes[name], module.__file__, "exec"), module.__dict__)
            modules[name] = module
        if _SOURCE_CACHE_ENABLED:
            signatures = {name: _module_signature(module) for name, module in modules.items()}
            _SOURCE_CACHE = (key, modules, signatures)
        return dict(modules), records


def _recheck(records):
    for row in records.values():
        data = Path(row["path"]).read_bytes()
        if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("bound source changed during phase routing")
    with _SOURCE_CACHE_LOCK:
        _check_cached_globals()


def _split(pair, retained, total):
    """Mix first; split the smaller part to retain tiny, positive overflow."""
    if retained == total:
        return pair, (0., 0.)
    if retained == 0:
        return (0., 0.), pair
    if not 0 < retained < total:
        raise ValueError("invalid internal volume split")
    if retained <= total / 2:
        fraction = float(retained / total)
        keep = tuple(v * fraction for v in pair)
        leave = tuple(v - k for v, k in zip(pair, keep))
        small = keep
    else:
        fraction = float((total - retained) / total)
        leave = tuple(v * fraction for v in pair)
        keep = tuple(v - e for v, e in zip(pair, leave))
        small = leave
    if fraction == 0 or any(v > 0 and part == 0 for v, part in zip(pair, small)):
        raise ValueError("positive phase split underflows binary64")
    for original, k, e in zip(pair, keep, leave):
        _check(_sum((k, e)) - original, original)
    return keep, leave


def _distribute(total, weights):
    """Geometric proportional allocation; expose, never hide, rounding residual."""
    represented = _sum(weights)
    if total == 0:
        return [0.] * len(weights), 0.
    if represented <= 0:
        raise ValueError("positive phase inventory has no geometric wet volume")
    result = [total * (v / represented) for v in weights]
    if any(weight > 0 and value == 0 for weight, value in zip(weights, result)):
        raise ValueError("positive phase allocation underflows binary64")
    # One local remainder maintains the supplied inventory; correction is
    # reported in the pool's allocation residual and checked against its scale.
    pivot = max(range(len(weights)), key=lambda i: (weights[i], -i))
    others = _sum(v for i, v in enumerate(result) if i != pivot)
    old = result[pivot]
    result[pivot] = _number(total - others, "phase allocation remainder", nonnegative=True)
    adjustment = result[pivot] - old
    _check(adjustment, total)
    _check(_sum(result) - total, total)
    return result, adjustment


def _ulp(value):
    """One-ULP arithmetic bound; exact zero-only operations need no budget."""
    return Fraction(math.ulp(value)) if value else Fraction()


def _upper_bound(value):
    """Round an error certificate upward, never a stock or geometric value."""
    if value == 0:
        return Fraction()
    rounded = _number(float(value), "roundoff certificate", nonnegative=True)
    if Fraction(rounded) < value:
        rounded = math.nextafter(rounded, math.inf)
    return Fraction(_number(rounded, "upward roundoff certificate", nonnegative=True))


def _split_bounds(pair, retained, total, keep, leave, incoming_error):
    """Predeclared absolute mixture-error propagation for _split operations.

    Each fsum/product/subtraction gets one ULP (conservative versus nearest
    rounding, including fsum's possible final double rounding). Ratio error is
    propagated by the actual multiplier. Retained and overflow ideal fractions
    multiply the incoming certificate. No observed residual sets this budget.
    """
    if retained == total:
        return incoming_error, Fraction()
    if retained == 0:
        return Fraction(), incoming_error
    small_ratio = min(retained, total-retained)/total
    fraction = float(small_ratio)
    small = keep if retained <= total/2 else leave
    large = leave if retained <= total/2 else keep
    product_error = sum((Fraction(v)*_ulp(fraction)+_ulp(a) for v, a in zip(pair, small)), Fraction())
    subtraction_error = sum((_ulp(v) for v in large), Fraction())
    if retained <= total/2:
        ke, le = product_error, product_error+subtraction_error
    else:
        ke, le = product_error+subtraction_error, product_error
    return (_upper_bound(incoming_error*(retained/total)+ke),
            _upper_bound(incoming_error*((total-retained)/total)+le))


def _allocation_bound(values, weights):
    # Because the pivot is total - fsum(other *already rounded* values), their
    # proportional multiplication/division errors cancel from the total. Only
    # the final nonpivot fsum and pivot subtraction affect total phase stock.
    if not any(values) or len(values) == 1:
        return Fraction()
    pivot = max(range(len(weights)), key=lambda i: (weights[i], -i))
    return _ulp(_sum(v for i, v in enumerate(values) if i != pivot)) + _ulp(values[pivot])


def _canonical_liquid_anchor(values, target, weights):
    """Make the rounded aggregate a fixed point, with an arithmetic bound.

    Correct the largest entry towards target - exact_sum(others). Candidate
    rounding and its immediate neighbours cover the rounding-cell endpoints;
    no search in physical parameter space or repeated ULP stepping is used.
    """
    if _sum(values) == target:
        return Fraction()
    original = list(values)
    exact_sum = sum(map(Fraction, values), Fraction())
    i = max(range(len(values)), key=lambda j: (values[j], -j))
    ideal = Fraction(values[i])+Fraction(target)-exact_sum
    if ideal <= 0:
        raise UnsupportedPhaseRouting("canonical liquid anchor cannot retain a positive carrier")
    nearest = float(ideal)
    for candidate in (nearest, math.nextafter(nearest, -math.inf), math.nextafter(nearest, math.inf)):
        if not math.isfinite(candidate) or candidate <= 0:
            continue
        trial = list(original)
        trial[i] = candidate
        if _sum(trial) == target:
            certificate = _allocation_bound(original, weights)+_ulp(candidate)
            if abs(Fraction(candidate)-Fraction(original[i])) > certificate:
                raise ValueError("canonical liquid anchor exceeds allocation arithmetic bound")
            values[:] = trial
            return certificate
    raise UnsupportedPhaseRouting("canonical full-sill liquid aggregate is not representable")


def _exact_capacity_allocation(wr, sr, weights, capacity, error_bound, liquid_anchor):
    """Repair ONLY exactly representable bounded phase-output roundoff.

    No water is moved to exports, no bed/level is altered, and no below-capacity
    substitute is accepted. Liquid is the canonical mixed-pool anchor. The
    exact remaining suspended volume is redistributed before correcting its
    final representable remainder. Thus a roundoff correction does not cause
    an extra rehomogenisation on the next call. Pure liquid is separate.
    """
    exact_total = sum((Fraction(v) for values in (wr, sr) for v in values), Fraction())
    delta = capacity-exact_total
    if abs(delta) > error_bound:
        raise ValueError("full-sill phase error exceeds arithmetic ULP certificate")
    evidence = {"exact_capacity_matched": True, "adjustment_liquid_m3": 0.,
                "adjustment_suspended_solid_m3": 0., "exact_adjustment": {"numerator": delta.numerator,
                "denominator": delta.denominator}, "arithmetic_bound_m3": float(error_bound),
                "cell_offset": None, "physical_transfer": False,
                "canonical_anchor": "liquid" if any(sr) else "pure_liquid",
                "cell_adjustments": [], "canonical_remainder_bound_m3": 0.}
    if delta == 0 and (not any(sr) or _sum(wr) == liquid_anchor):
        return evidence
    before_w, before_s = list(wr), list(sr)
    phase, values = ("suspended_solid", sr) if any(sr) else ("liquid", wr)
    liquid_bound = Fraction()
    if any(sr):
        liquid_bound = _canonical_liquid_anchor(wr, liquid_anchor, weights)
        target_total = capacity-sum(map(Fraction, wr), Fraction())
        if target_total <= 0:
            raise UnsupportedPhaseRouting("full-sill suspended remainder cannot preserve positive phases")
        target_float = _float(target_total)
        replacement, _ = _distribute(target_float, weights)
        sr[:] = replacement
        remainder_bound = _upper_bound(_ulp(target_float)+_allocation_bound(sr, weights))
        evidence["canonical_remainder_bound_m3"] = float(remainder_bound)
    else:
        remainder_bound = error_bound
    remainder = capacity-sum((Fraction(v) for a in (wr, sr) for v in a), Fraction())
    if abs(remainder) > remainder_bound:
        raise ValueError("canonical phase remainder exceeds its arithmetic certificate")
    if remainder:
        for i in sorted(range(len(values)), key=lambda j: (math.ulp(values[j]), j)):
            if values[i] <= 0:
                continue
            target = Fraction(values[i])+remainder
            if target <= 0:
                continue
            candidate = float(target)
            if math.isfinite(candidate) and Fraction(candidate) == target:
                values[i] = candidate
                evidence["cell_offset"] = i
                break
        else:
            raise UnsupportedPhaseRouting("full-sill phase capacity has no bounded exact binary64 representation")
    if sum((Fraction(v) for a in (wr, sr) for v in a), Fraction()) != capacity:
        raise ValueError("exact output correction did not match capacity")
    for label, before, after in (("liquid", before_w, wr), ("suspended_solid", before_s, sr)):
        correction = sum((Fraction(a)-Fraction(b) for a, b in zip(after, before)), Fraction())
        phase_bound = liquid_bound if label == "liquid" and any(before_s) else error_bound+liquid_bound
        if abs(correction) > phase_bound:
            raise ValueError("phase-specific representation correction exceeds arithmetic bound")
        evidence["adjustment_"+label+"_m3"] = float(correction)
        evidence["adjustment_"+label+"_bound_m3"] = float(_upper_bound(phase_bound))
        _check(float(correction), _sum(before), _sum(after))
        for i, (a, b) in enumerate(zip(after, before)):
            if a != b:
                evidence["cell_adjustments"].append({"phase": label, "cell_offset": i,
                    "before_m3": b, "after_m3": a, "adjustment_m3": float(Fraction(a)-Fraction(b))})
    return evidence


def _exact_stage(bed, area, volume):
    """Exact sorted piecewise-linear inverse on already validated Fractions.

    Accumulate geometric intervals before rounding the final elevation once.
    No spill clamp or epsilon is applied; rounding is a monotone conversion.
    """
    if volume <= 0:
        raise ValueError("positive exact stage-inversion volume required")
    pairs = sorted(zip(bed, area))
    level, wet_area, remaining = pairs[0][0], Fraction(), volume
    for next_level, a in pairs:
        needed = (next_level - level) * wet_area
        if wet_area and remaining <= needed:
            return level + remaining / wet_area
        remaining -= needed
        level = next_level
        wet_area += a
    return level + remaining / wet_area


def _connected(cells, shape, connectivity):
    wet = set(cells)
    if not wet:
        return True
    rows, cols = shape
    first = min(wet)
    seen, stack = {first}, [first]
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    if connectivity == 8:
        offsets += ((-1, -1), (-1, 1), (1, -1), (1, 1))
    while stack:
        i = stack.pop()
        r, c = divmod(i, cols)
        for dr, dc in offsets:
            rr, cc = r + dr, c + dc
            j = rr * cols + cc
            if 0 <= rr < rows and 0 <= cc < cols and j in wet and j not in seen:
                seen.add(j)
                stack.append(j)
    return seen == wet


def route_phases(bed_m, area_m2, shape, outlets, liquid_m3, suspended_solid_m3, *, connectivity=4):
    """Route cell W/S inventories through numerical basins, preserving the bed.

    Closed or explicit native-edge outlets only. The returned free surface is
    shared by liquid and suspended particles; liquid-equivalent depth is not a
    second physical surface. All leaf inventories are loaded before overflow
    processing in ascending leaf-ID order. Geometrically full siblings at an
    exactly dry saddle do not mix. A positive-head union must have represented
    positive-depth connectivity. This is not continuous-time hydraulics.
    """
    bed = _list(bed_m, "bed_m")
    area = _list(area_m2, "area_m2", positive=True)
    liquid = _list(liquid_m3, "liquid_m3", nonnegative=True)
    solid = _list(suspended_solid_m3, "suspended_solid_m3", nonnegative=True)
    n = len(bed)
    if any(len(a) != n for a in (area, liquid, solid)):
        raise ValueError("per-cell array lengths differ")
    if any(s > 0 and w == 0 for w, s in zip(liquid, solid)):
        raise ValueError("dry suspended solids require a separately declared emplacement transfer")
    modules, binding = _bound_sources()
    try:
        topology = modules["basin_topology.py"].extract_basin_topology(
            bed, shape, outlets, connectivity=connectivity)
        geometry = modules["water.py"]
        basins = topology["basins"]
        leaves = sorted(topology["leaf_ids"])
        if basins:
            # Preserve R2's complete ownership/root/geographic-receiver checks.
            geometry.fill_spill_merge(bed, area, basins, dict.fromkeys(leaves, 0.),
                                      **topology["storage_options"])
        rows = {row["id"]: row for row in basins}
        parent = {child: row["id"] for row in basins for child in row["children"]}
        # All operands are exact rationals of supplied binary64 values. This
        # makes equal-sill child sums and flat parent capacity IDENTICAL without
        # changing phase volumes or introducing an epsilon terrain height.
        fbed, farea = list(map(Fraction, bed)), list(map(Fraction, area))
        capacity = {}
        for name, row in rows.items():
            level = row["spill_m"]
            capacity[name] = (None if level is None else
                              sum((max(Fraction(level) - fbed[i], 0) * farea[i]
                                   for i in row["cell_indices"]), Fraction()))
            if capacity[name] is not None:
                _float(capacity[name])
        volumes = {name: Fraction() for name in rows}
        phases = {name: (0., 0.) for name in rows}
        errors = {name: Fraction() for name in rows}
        groups = {name: [] for name in leaves}
        direct = []
        for i, leaf in enumerate(topology["cell_to_leaf"]):
            (direct if leaf is None else groups[leaf]).append(i)
        # These are durable inventories, not future injections. Downstream
        # pre-existing phases must be present before any upstream spill arrives.
        for leaf in leaves:
            cells = groups[leaf]
            volumes[leaf] = sum((Fraction(liquid[i]) + Fraction(solid[i]) for i in cells), Fraction())
            phases[leaf] = (_sum(liquid[i] for i in cells), _sum(solid[i] for i in cells))
            errors[leaf] = sum((_ulp(v) for v in phases[leaf]), Fraction())
        exported_w = [liquid[i] for i in direct]
        exported_s = [solid[i] for i in direct]
        exact_direct = sum((Fraction(liquid[i]) + Fraction(solid[i]) for i in direct), Fraction())
        exact_export = exact_direct
        ready, mixed, events = set(), set(), []

        def active(name):
            result = name
            while name in parent and parent[name] in ready:
                name = parent[name]
                if name in mixed:
                    result = name
            return result

        def constituents(name):
            """Current hydraulic compartments, not ready bookkeeping unions."""
            answer, pending = [], [name]
            while pending:
                item = pending.pop()
                if item in mixed or not rows[item]["children"]:
                    answer.append(item)
                else:
                    pending.extend(reversed(rows[item]["children"]))
            return answer

        def full(name):
            return capacity[name] is not None and volumes[name] == capacity[name]

        for leaf in leaves:
            name, steps = active(leaf), 0
            amount, pair = Fraction(), (0., 0.)
            amount_error = Fraction()
            if not volumes[name]:
                continue
            while True:
                steps += 1
                if steps > 4 * len(rows) + 4 or len(events) >= MAX_TRANSFERS:
                    raise ValueError("bounded phase spill traversal did not progress")
                name = active(name)
                virtual = name in ready and name not in mixed
                if virtual and amount and (capacity[name] is None or capacity[name] > volumes[name]):
                    # Positive head above the common saddle makes all ready
                    # descendants one hydraulic pool. No excess => no mixing.
                    parts = constituents(name)
                    phases[name] = tuple(_sum(phases[item][k] for item in parts) for k in (0, 1))
                    errors[name] = _upper_bound(sum((errors[item] for item in parts), Fraction())+
                                                sum((_ulp(v) for v in phases[name]), Fraction()))
                    exact_total = volumes[name] + amount
                    keep = exact_total if capacity[name] is None else min(exact_total, capacity[name])
                    eta = _exact_stage([fbed[i] for i in rows[name]["cell_indices"]],
                                       [farea[i] for i in rows[name]["cell_indices"]], keep)
                    merge_level = Fraction(rows[rows[name]["children"][0]]["spill_m"])
                    if eta <= merge_level:
                        raise ValueError("positive-head promotion has no exact head")
                    try:
                        represented_eta = _number(float(eta), "joined stage")
                    except OverflowError as exc:
                        raise ValueError("joined stage exceeds binary64") from exc
                    if represented_eta <= float(merge_level):
                        raise UnsupportedPhaseRouting("positive saddle connection is not representable")
                    mixed.add(name)
                    virtual = False
                    events.append({"kind": "positive_depth_join", "basin": name,
                                   "from_pools": parts, "merge_level_m": float(merge_level)})
                if not virtual:
                    total = volumes[name] + amount
                    combined = tuple(_sum((a, b)) for a, b in zip(phases[name], pair))
                    combined_error = _upper_bound(errors[name]+amount_error+
                                                  sum((_ulp(v) for v in combined), Fraction()))
                    total_float = _float(total)
                    _check(_sum(combined) - total_float, total_float)
                    keep_volume = total if capacity[name] is None else min(total, capacity[name])
                    keep, overflow = _split(combined, keep_volume, total)
                    errors[name], amount_error = _split_bounds(combined, keep_volume, total,
                                                               keep, overflow, combined_error)
                    volumes[name], phases[name] = keep_volume, keep
                    amount, pair = total - keep_volume, overflow
                # Otherwise this equal-height interval has no storage head.
                # Only its excess parcel transits; daughter phases stay owned.
                if name in parent:
                    up = parent[name]
                    left, right = rows[up]["children"]
                    if full(left) and full(right):
                        if up not in ready:
                            ready.add(up)
                            volumes[up] = volumes[left] + volumes[right]
                            errors[up] = _upper_bound(errors[left]+errors[right])
                            events.append({"kind": "geometric_ready_no_mixing", "basin": up,
                                           "children": [left, right], "stage_m": rows[left]["spill_m"]})
                        name = up
                        continue
                if not amount:
                    break
                target = rows[name]["spill_to_leaf"]
                if name in ready and name not in mixed and name not in parent:
                    raise UnsupportedPhaseRouting("compound zero-head throughflow requires a separate flux closure",
                                                  basin_id=name, cell_indices=list(rows[name]["cell_indices"]),
                                                  spill_m=rows[name]["spill_m"])
                events.append({"kind": "spill", "from": name, "to_leaf": target,
                               "mixture_m3": _float(amount), "liquid_m3": pair[0],
                               "suspended_solid_m3": pair[1]})
                if target is None:
                    exact_export += amount
                    exported_w.append(pair[0])
                    exported_s.append(pair[1])
                    break
                name = target

        active_ids = sorted(name for name, row in rows.items() if active(name) == name and
                            (not row["children"] or name in mixed))
        out_w, out_s, depth = [0.] * n, [0.] * n, [0.] * n
        surface, pools = [None] * n, []
        exact_stored = Fraction()
        for name in active_ids:
            row, cells = rows[name], rows[name]["cell_indices"]
            v = _float(volumes[name])
            w, s = phases[name]
            if v == 0:
                eta, exact_eta, ds = None, None, [0.] * len(cells)
            elif full(name):
                eta = row["spill_m"]
                exact_eta = Fraction(eta)
                ds = [_number(max(eta - bed[i], 0.), "depth", nonnegative=True) for i in cells]
            else:
                exact_eta = _exact_stage([fbed[i] for i in cells], [farea[i] for i in cells], volumes[name])
                if row["spill_m"] is not None and exact_eta > Fraction(row["spill_m"]):
                    raise ValueError("exact stage inversion exceeded exact spill capacity")
                try:
                    eta = _number(float(exact_eta), "stage")
                except OverflowError as exc:
                    raise ValueError("stage exceeds binary64") from exc
                if row["spill_m"] is not None and eta > row["spill_m"]:
                    raise ValueError("non-monotone exact-stage conversion")
                ds = [_number(max(eta - bed[i], 0.), "depth", nonnegative=True) for i in cells]
            exact_wet = [] if exact_eta is None else [i for i in cells if fbed[i] < exact_eta]
            represented_wet = [i for i, d in zip(cells, ds) if d > 0]
            if exact_wet != represented_wet:
                raise UnsupportedPhaseRouting("positive-depth wet transition is not representable")
            if not _connected(represented_wet, shape, connectivity):
                raise UnsupportedPhaseRouting("hydraulic pool has disconnected positive-depth cells")
            weights = [_number(d * area[i], "geometric cell volume", nonnegative=True)
                       for i, d in zip(cells, ds)]
            represented = _sum(weights)
            (wr, wa), (sr, sa) = _distribute(w, weights), _distribute(s, weights)
            representation = None
            if v > 0 and full(name):
                allocation_error = _upper_bound(errors[name]+_allocation_bound(wr, weights)+
                                                _allocation_bound(sr, weights))
                representation = _exact_capacity_allocation(wr, sr, weights, volumes[name], allocation_error, w)
            if any(b > 0 and a == 0 for a, b in zip(wr, sr)):
                raise ValueError("phase allocation cannot represent a positive liquid carrier")
            for i, d, wi, si in zip(cells, ds, wr, sr):
                depth[i], out_w[i], out_s[i] = d, wi, si
                surface[i] = eta if d > 0 else None
                _check(_sum((wi, si)) - d * area[i], wi, si, d * area[i])
            pools.append({"id": name, "cell_indices": list(cells),
                          "wet_cell_indices": [i for i, d in zip(cells, ds) if d > 0],
                          "stage_m": eta, "liquid_m3": _sum(wr), "suspended_solid_m3": _sum(sr),
                          "mixture_m3": v, "solid_volume_fraction": _sum(sr) / _sum((*wr, *sr)) if w or s else 0.,
                          "spill_m": row["spill_m"],
                          "geometry_residual_m3": _check(represented - v, represented, v),
                          "phase_representation_residual_m3": _check(_sum((*wr, *sr)) - v, w, s, v),
                          "pre_output_representation_liquid_m3": w,
                          "pre_output_representation_suspended_solid_m3": s,
                          "liquid_allocation_adjustment_m3": wa,
                          "solid_allocation_adjustment_m3": sa,
                          "liquid_allocation_residual_m3": _check(_sum(wr) - w, w),
                          "solid_allocation_residual_m3": _check(_sum(sr) - s, s)})
            pools[-1]["full_sill_representation"] = representation
            exact_stored += volumes[name]
        input_w, input_s = _sum(liquid), _sum(solid)
        stored_w, stored_s = _sum(out_w), _sum(out_s)
        export_w, export_s = _sum(exported_w), _sum(exported_s)
        exact_input = sum((Fraction(w) + Fraction(s) for w, s in zip(liquid, solid)), Fraction())
        if exact_input != exact_stored + exact_export:
            raise ValueError("exact geometric routing volume ledger failed")
        ledger = {
            "input_liquid_m3": input_w, "input_suspended_solid_m3": input_s,
            "stored_liquid_m3": stored_w, "stored_suspended_solid_m3": stored_s,
            "exported_liquid_m3": export_w, "exported_suspended_solid_m3": export_s,
            "liquid_residual_m3": _check(_sum((stored_w, export_w)) - input_w, input_w, stored_w, export_w),
            "suspended_solid_residual_m3": _check(_sum((stored_s, export_s)) - input_s, input_s, stored_s, export_s),
            "geometry_residual_m3": _check(_sum(d * a for d, a in zip(depth, area)) - _float(exact_stored),
                                           _float(exact_stored)),
            "exact_mixture_routing_residual_m3": 0.,
            "direct_export_liquid_m3": _sum(liquid[i] for i in direct),
            "direct_export_suspended_solid_m3": _sum(solid[i] for i in direct),
            "volume_atol_m3": VOLUME_ATOL, "volume_rtol": RTOL,
            "liquid_representation_adjustment_m3": _sum(p["full_sill_representation"]["adjustment_liquid_m3"]
                                                         for p in pools if p["full_sill_representation"]),
            "suspended_solid_representation_adjustment_m3": _sum(p["full_sill_representation"]["adjustment_suspended_solid_m3"]
                                                                  for p in pools if p["full_sill_representation"]),
        }
        return {"status": "PASS_NUMERICAL_CONNECTED_PHASE_STORAGE_ONLY", "liquid_m3": out_w,
                "suspended_solid_m3": out_s, "mixture_depth_m": depth, "water_surface_m": surface,
                "liquid_equivalent_depth_m": [_number(w / a, "liquid equivalent depth", nonnegative=True)
                                               for w, a in zip(out_w, area)],
                "active_pools": pools, "exported_liquid_m3": export_w,
                "exported_suspended_solid_m3": export_s, "ledger": ledger,
                "topology": topology, "source_binding": binding, "events": events,
                "assumptions": {"porosity": 0., "material_classes": 1,
                                "mixing": "PRELOAD_ALL_LEAVES_MIX_ONLY_POSITIVE_DEPTH_UNIONS",
                                "equal_sill_full_siblings_mix": False,
                                "compound_zero_head_throughflow": "UNSUPPORTED",
                                "time_integration": False, "settling_applied": False,
                                "physical_bed_changed": False, "hydraulics_solved": False,
                                "physical_depression_origin": "UNRESOLVED", "production_authorised": False}}
    finally:
        _recheck(binding)
