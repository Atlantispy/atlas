"""Bounded two-phase, well-mixed basin storage; no time integration or bed edits.

R2 geometry is loaded from hash-pinned source bytes, without importing a mutable
module by name. All phase inputs are cell inventories, not rates. See methods.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import math
from pathlib import Path
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


def _bound_sources():
    records, modules = {}, {}
    for name, expected in SOURCE_PINS.items():
        path = _BASE.parent / "terrain_model_r2" / name
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected:
            raise ValueError("frozen R2 source identity mismatch: " + name)
        module = types.ModuleType("_r3_bound_" + path.stem)
        module.__file__ = str(path)
        exec(compile(data, str(path), "exec"), module.__dict__)
        records[name] = {"path": str(path), "sha256": digest, "size_bytes": len(data)}
        modules[name] = module
    design = _BASE / "CAPTURE_DESIGN.md"
    data = design.read_bytes()
    if hashlib.sha256(data).hexdigest() != DESIGN_SHA256:
        raise ValueError("frozen capture design identity mismatch")
    records["CAPTURE_DESIGN.md"] = {
        "path": str(design), "sha256": DESIGN_SHA256, "size_bytes": len(data)}
    return modules, records


def _recheck(records):
    for row in records.values():
        data = Path(row["path"]).read_bytes()
        if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("bound source changed during phase routing")


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


def route_phases(bed_m, area_m2, shape, outlets, liquid_m3, suspended_solid_m3, *, connectivity=4):
    """Route cell W/S inventories through numerical basins, preserving the bed.

    Closed or explicit native-edge outlets only. The returned free surface is
    shared by liquid and suspended particles; liquid-equivalent depth is not a
    second physical surface. All leaf inventories are loaded before overflow
    processing in ascending leaf-ID order. This is deterministic batch mixing,
    not continuous-time hydraulics.
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
        exported_w = [liquid[i] for i in direct]
        exported_s = [solid[i] for i in direct]
        exact_direct = sum((Fraction(liquid[i]) + Fraction(solid[i]) for i in direct), Fraction())
        exact_export = exact_direct
        merged, events = set(), []

        def active(name):
            while name in parent and parent[name] in merged:
                name = parent[name]
            return name

        def full(name):
            return capacity[name] is not None and volumes[name] == capacity[name]

        for leaf in leaves:
            name, steps = active(leaf), 0
            amount, pair = Fraction(), (0., 0.)
            if not volumes[name]:
                continue
            while True:
                steps += 1
                if steps > 4 * len(rows) + 4 or len(events) >= MAX_TRANSFERS:
                    raise ValueError("bounded phase spill traversal did not progress")
                name = active(name)
                total = volumes[name] + amount
                combined = tuple(_sum((a, b)) for a, b in zip(phases[name], pair))
                total_float = _float(total)
                _check(_sum(combined) - total_float, total_float)
                keep_volume = total if capacity[name] is None else min(total, capacity[name])
                keep, overflow = _split(combined, keep_volume, total)
                volumes[name], phases[name] = keep_volume, keep
                amount, pair = total - keep_volume, overflow
                if name in parent:
                    up = parent[name]
                    left, right = rows[up]["children"]
                    if full(left) and full(right):
                        if up in merged:
                            raise ValueError("internal duplicate basin promotion")
                        merged.add(up)
                        volumes[up] = volumes[left] + volumes[right]
                        phases[up] = tuple(_sum((a, b)) for a, b in zip(phases[left], phases[right]))
                        events.append({"kind": "merge", "basin": up, "children": [left, right],
                                       "stage_m": rows[left]["spill_m"]})
                        # Cascade even with zero excess: equal-level joins must
                        # mix all full descendants, not depend on another input.
                        name = up
                        continue
                if not amount:
                    break
                target = rows[name]["spill_to_leaf"]
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
                            (not row["children"] or name in merged))
        out_w, out_s, depth = [0.] * n, [0.] * n, [0.] * n
        surface, pools = [None] * n, []
        exact_stored = Fraction()
        for name in active_ids:
            row, cells = rows[name], rows[name]["cell_indices"]
            v = _float(volumes[name])
            w, s = phases[name]
            if v == 0:
                eta, ds = None, [0.] * len(cells)
            elif full(name):
                eta = row["spill_m"]
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
            weights = [_number(d * area[i], "geometric cell volume", nonnegative=True)
                       for i, d in zip(cells, ds)]
            represented = _sum(weights)
            (wr, wa), (sr, sa) = _distribute(w, weights), _distribute(s, weights)
            if any(b > 0 and a == 0 for a, b in zip(wr, sr)):
                raise ValueError("phase allocation cannot represent a positive liquid carrier")
            for i, d, wi, si in zip(cells, ds, wr, sr):
                depth[i], out_w[i], out_s[i] = d, wi, si
                surface[i] = eta if d > 0 else None
                _check(_sum((wi, si)) - d * area[i], wi, si, d * area[i])
            pools.append({"id": name, "cell_indices": list(cells),
                          "wet_cell_indices": [i for i, d in zip(cells, ds) if d > 0],
                          "stage_m": eta, "liquid_m3": w, "suspended_solid_m3": s,
                          "mixture_m3": v, "solid_volume_fraction": s / _sum((w, s)) if w or s else 0.,
                          "spill_m": row["spill_m"],
                          "geometry_residual_m3": _check(represented - v, represented, v),
                          "phase_representation_residual_m3": _check(_sum((w, s)) - v, w, s, v),
                          "liquid_allocation_adjustment_m3": wa,
                          "solid_allocation_adjustment_m3": sa,
                          "liquid_allocation_residual_m3": _check(_sum(wr) - w, w),
                          "solid_allocation_residual_m3": _check(_sum(sr) - s, s)})
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
        }
        return {"status": "PASS_NUMERICAL_PHASE_STORAGE_ONLY", "liquid_m3": out_w,
                "suspended_solid_m3": out_s, "mixture_depth_m": depth, "water_surface_m": surface,
                "liquid_equivalent_depth_m": [_number(w / a, "liquid equivalent depth", nonnegative=True)
                                               for w, a in zip(out_w, area)],
                "active_pools": pools, "exported_liquid_m3": export_w,
                "exported_suspended_solid_m3": export_s, "ledger": ledger,
                "topology": topology, "source_binding": binding, "events": events,
                "assumptions": {"porosity": 0., "material_classes": 1,
                                "mixing": "PRELOAD_ALL_LEAF_INVENTORIES_THEN_ASCENDING_LEAF_OVERFLOW",
                                "time_integration": False, "settling_applied": False,
                                "physical_bed_changed": False, "hydraulics_solved": False,
                                "physical_depression_origin": "UNRESOLVED", "production_authorised": False}}
    finally:
        _recheck(binding)
