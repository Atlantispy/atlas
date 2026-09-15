"""Deterministic, non-promoting History A structural/motion snapshot products.

This read-only layer verifies its four consumed package files against the package's
own manifest. The caller must independently bind that manifest and every supplied
decision/source pin to actual authority. A supplied status string is never approval.
No legacy generator, raster, historical velocity inference or time evolution runs.

Decision schema v1 is deliberately strict; see ``DECISION_KEYS`` and the synthetic
tests. Component velocities describe structural blocks, not rigid tectonic plates.
All vectors share a supplied fixed reference frame; coordinates are x-east/y-south.
Right minus left is a declaration-based difference, not a fault-slip measurement.
Right-normal = (-dy,+dx), left-normal = (+dy,-dx), following trace coordinate order.
Neither sidedness, convergence nor dextral/sinistral motion is inferred here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import stat
from typing import Any


FRAME = "diadem_local_grid_x_east_y_south"
UNITS = "mm/year"
PREFIX = "checkpoint1-history-a-"
MANIFEST = "checkpoint1-event-model-shared-manifest-review-only.json"
FILES = {"faults_blocks": PREFIX + "faults-blocks.geojson",
         "events": PREFIX + "events.json", "lineage": PREFIX + "lineage.json"}
PRODUCT_NAMES = ("tectonic-structural-domain-crosswalk.geojson",
                 "tectonic-fault-relationships.geojson", "tectonic-snapshot-motion.json")
DECISION_KEYS = {"schema_version", "snapshot_id", "snapshot_source_refs", "frame",
                 "reference_frame", "frame_source_refs", "velocity_units", "source_status",
                 "source_refs", "blocks", "faults"}
MAX_JSON_BYTES = 16 * 1024 * 1024


class SnapshotError(ValueError):
    """Malformed, inconsistent or unsupported snapshot input."""


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise SnapshotError(f"{label} must be nonblank text")
    return value


def _keys(value: Any, expected: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != expected:
        raise SnapshotError(f"{label} keys must be exactly {sorted(expected)}")
    return value


def _json_tree(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_tree(item)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for item in value.values():
            _json_tree(item)
        return
    raise SnapshotError("input must be a finite, plain JSON tree")


def _pairs(items: list[tuple[str, Any]]) -> dict:
    value = {}
    for key, item in items:
        if key in value:
            raise SnapshotError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _plain(path: Path) -> None:
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SnapshotError(f"linked/reparse input: {part}")


def _read(path: Path) -> tuple[dict, dict]:
    _plain(path)
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise SnapshotError(f"not a bounded JSON file: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        raise SnapshotError(f"JSON grew beyond bound: {path}")
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid JSON: {path}") from exc
    _json_tree(value)
    if type(value) is not dict:
        raise SnapshotError(f"expected JSON object: {path}")
    return value, {"file": path.name, "bytes": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest()}


def _number(value: Any, label: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if type(value) not in (int, float):
        raise SnapshotError(f"{label} must be a finite number or an allowed null")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise SnapshotError(f"{label} is not representable") from exc
    if not math.isfinite(result):
        raise SnapshotError(f"{label} must be finite")
    return result


def _refs(value: Any, sources: dict, label: str, *, required: bool) -> list[str]:
    if type(value) is not list or any(type(v) is not str for v in value):
        raise SnapshotError(f"{label} must be source IDs")
    if len(set(value)) != len(value) or any(v not in sources for v in value):
        raise SnapshotError(f"{label} has duplicate or unresolved source IDs")
    if required and not value:
        raise SnapshotError(f"{label} needs a located source")
    return value


def _decisions(value: dict | None, block_ids: set[str], fault_ids: set[str]) -> dict | None:
    if value is None:
        return None
    _json_tree(value)
    _keys(value, DECISION_KEYS, "decisions")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise SnapshotError("unsupported decision schema version")
    for key in ("snapshot_id", "reference_frame", "source_status"):
        _text(value[key], key)
    if value["frame"] != FRAME or value["velocity_units"] != UNITS:
        raise SnapshotError("unsupported coordinate frame or velocity units")
    if type(value["source_refs"]) is not list:
        raise SnapshotError("source_refs must be a list")
    sources = {}
    for source in value["source_refs"]:
        _keys(source, {"id", "path", "sha256", "status", "locator"}, "source")
        for key in ("id", "path", "status", "locator"):
            _text(source[key], f"source {key}")
        if not re.fullmatch(r"[0-9a-f]{64}", source["sha256"] if type(source["sha256"]) is str else ""):
            raise SnapshotError("source SHA-256 must be lowercase hexadecimal")
        if not Path(source["path"]).is_absolute():
            raise SnapshotError("source path must be absolute")
        if source["id"] in sources:
            raise SnapshotError("duplicate source ID")
        sources[source["id"]] = source
    _refs(value["snapshot_source_refs"], sources, "snapshot_source_refs", required=True)
    _refs(value["frame_source_refs"], sources, "frame_source_refs", required=True)
    for category, allowed in (("blocks", block_ids), ("faults", fault_ids)):
        if type(value[category]) is not list:
            raise SnapshotError(f"{category} must be a list")
        seen = set()
        for record in value[category]:
            if category == "blocks":
                _keys(record, {"block_id", "plate_id", "plate_identity_source_refs", "velocity"}, "block decision")
                record_id = record["block_id"]
                plate = record["plate_id"]
                if plate is not None:
                    _text(plate, "plate_id")
                _refs(record["plate_identity_source_refs"], sources, "plate identity sources", required=plate is not None)
                motion = record["velocity"]
                if motion is not None:
                    _keys(motion, {"vx", "vy", "frame", "reference_frame", "units", "source_refs"}, "velocity")
                    if (motion["frame"] != FRAME or motion["reference_frame"] != value["reference_frame"]
                            or motion["units"] != UNITS):
                        raise SnapshotError("mismatched velocity frame/reference frame/units")
                    for component in ("vx", "vy"):
                        _number(motion[component], component, nullable=True)
                    _refs(motion["source_refs"], sources, "motion sources",
                          required=motion["vx"] is not None or motion["vy"] is not None)
            else:
                _keys(record, {"fault_id", "plate_boundary", "source_refs"}, "fault decision")
                record_id = record["fault_id"]
                boundary = record["plate_boundary"]
                if boundary is not None and type(boundary) is not bool:
                    raise SnapshotError("plate_boundary must be bool or null")
                _refs(record["source_refs"], sources, "boundary sources", required=boundary is not None)
            if type(record_id) is not str or record_id not in allowed or record_id in seen:
                raise SnapshotError(f"duplicate/unresolved {category} ID")
            seen.add(record_id)
    return copy.deepcopy(value)


def _vector(vx: Any, vy: Any) -> dict:
    x, y = _number(vx, "vx", nullable=True), _number(vy, "vy", nullable=True)
    speed = bearing = None
    if x is not None and y is not None:
        speed = _number(math.hypot(x, y), "derived speed")
        # Clockwise from geographic north; zero speed has no direction.
        if speed != 0.0:
            bearing = math.degrees(math.atan2(x, -y)) % 360.0
    return {"vx": x, "vy": y, "speed": speed, "bearing_clockwise_from_north_deg": bearing}


def _point(value: Any) -> tuple[float, float]:
    if type(value) is not list or len(value) != 2:
        raise SnapshotError("trace coordinates must be two-dimensional pairs")
    return _number(value[0], "trace x"), _number(value[1], "trace y")


def _segments(coordinates: list, relative: dict) -> list[dict]:
    if type(coordinates) is not list or len(coordinates) < 2:
        raise SnapshotError("fault trace needs at least two coordinates")
    result = []
    for index, (a, b) in enumerate(zip(coordinates, coordinates[1:])):
        ax, ay = _point(a)
        bx, by = _point(b)
        dx, dy = _number(bx - ax, "trace dx"), _number(by - ay, "trace dy")
        length = _number(math.hypot(dx, dy), "segment length")
        tangent = right = None
        along = across = None
        if length > 0:
            tangent = [dx / length, dy / length]
            right = [-tangent[1], tangent[0]]
            if relative["vx"] is not None and relative["vy"] is not None:
                along = _number(relative["vx"] * tangent[0] + relative["vy"] * tangent[1], "tangential velocity")
                across = _number(relative["vx"] * right[0] + relative["vy"] * right[1], "right-normal velocity")
        result.append({"segment_index": index, "start_xy_km": copy.deepcopy(a), "end_xy_km": copy.deepcopy(b),
                       "length_km": length, "unit_tangent": tangent, "unit_right_normal": right,
                       "tangential_velocity": along, "right_normal_velocity": across,
                       "left_normal_velocity": None if across is None else -across,
                       "status": "DEGENERATE_SEGMENT" if length == 0 else
                                 ("UNKNOWN_MOTION" if along is None else "DERIVED_FROM_SUPPLIED_MOTION")})
    if not any(item["length_km"] > 0 for item in result):
        raise SnapshotError("fault trace has no finite nonzero segment")
    return result


def build_snapshot(package_dir: Path, domain_decisions: dict | None = None) -> dict:
    """Return ``{'products': {filename: payload}, 'validation': summary}``; write nothing.

    Missing evidence is represented by nulls and INCOMPLETE. Even complete supplied
    coverage is only COMPLETE_ENGINEERING_SNAPSHOT: the caller owns source authority,
    geometry audit, approval and the full-category gate. Input status labels survive.
    """
    package = Path(package_dir).absolute()
    _plain(package)
    manifest, manifest_pin = _read(package / MANIFEST)
    try:
        history = manifest["histories"]["A"]
        artifacts = history["artifacts"]
        source_status = _text(manifest["status"], "package status")
        _text(history["status"], "History A status")
        if manifest["authority"]["selected_history"] != "A":
            raise SnapshotError("only selected History A is supported")
    except (KeyError, TypeError) as exc:
        raise SnapshotError("missing History A manifest controls") from exc
    consumed = {}
    pins = [manifest_pin]
    for role, name in FILES.items():
        payload, pin = _read(package / name)
        try:
            expected = artifacts[role]
            if expected["path"] != f"work/stage4-rebuild/{name}" or expected["sha256"] != pin["sha256"]:
                raise SnapshotError(f"consumed input manifest mismatch: {role}")
        except (KeyError, TypeError) as exc:
            raise SnapshotError(f"missing consumed input binding: {role}") from exc
        consumed[role] = payload
        pins.append(pin)
    events, lineage, vectors = (consumed[k] for k in ("events", "lineage", "faults_blocks"))
    if events.get("history") != "A" or lineage.get("history") != "A":
        raise SnapshotError("consumed event/lineage history differs")
    if vectors.get("type") != "FeatureCollection" or type(vectors.get("features")) is not list:
        raise SnapshotError("fault/block input must be a FeatureCollection")
    blocks, faults = [], []
    for index, feature in enumerate(vectors["features"]):
        if type(feature) is not dict or feature.get("type") != "Feature" or type(feature.get("properties")) is not dict:
            raise SnapshotError("malformed source feature")
        layer = feature["properties"].get("layer")
        if layer == "structural_block":
            if feature.get("geometry", {}).get("type") not in ("Polygon", "MultiPolygon"):
                raise SnapshotError("structural block lacks polygon geometry")
            blocks.append((index, feature))
        elif layer == "fault_segment":
            if feature.get("geometry", {}).get("type") != "LineString":
                raise SnapshotError("finite fault lacks LineString geometry")
            faults.append((index, feature))
    block_ids = [item[1]["properties"].get("block_id") for item in blocks]
    fault_ids = [item[1]["properties"].get("fault_id") for item in faults]
    if (len(block_ids) != 10 or set(block_ids) != {f"A-B{i:02d}" for i in range(1, 11)}
            or len(fault_ids) != 44 or any(type(v) is not str or not v.strip() for v in fault_ids)
            or len(set(fault_ids)) != len(fault_ids)):
        raise SnapshotError("expected ten History A structural blocks and 44 unique finite faults")
    decisions = _decisions(domain_decisions, set(block_ids), set(fault_ids))
    block_decisions = {v["block_id"]: v for v in decisions["blocks"]} if decisions else {}
    fault_decisions = {v["fault_id"]: v for v in decisions["faults"]} if decisions else {}
    provenance = {"package_status": source_status, "history_status": history["status"],
                  "manifest_authority": copy.deepcopy(manifest["authority"]), "consumed_input_pins": pins,
                  "package_identity_gate": "CONSUMED_FILES_MATCH_SUPPLIED_MANIFEST_ONLY",
                  "source_claim_verification": "NOT_INDEPENDENTLY_AUTHORITY_VERIFIED",
                  "domain_decisions": decisions, "production_authorized": False}
    common = {"schema_version": 1, "product_status": "WORKING NON-CANON", "history": "A",
              "coordinate_frame": FRAME, "position_units": "km", "provenance": provenance}
    crosswalk, motion_blocks, motions, adjacency = [], [], {}, {v: [] for v in block_ids}
    for index, feature in blocks:
        block_id = feature["properties"]["block_id"]
        supplied = block_decisions.get(block_id, {})
        velocity = supplied.get("velocity") or {}
        vector = _vector(velocity.get("vx"), velocity.get("vy"))
        motions[block_id] = vector
        entry = {"block_id": block_id, "entity_type": "structural_block", "plate_id": supplied.get("plate_id"),
                 "plate_identity_status": "UNKNOWN" if supplied.get("plate_id") is None else "SUPPLIED_UNVERIFIED",
                 "plate_identity_source_refs": supplied.get("plate_identity_source_refs", []),
                 "source_feature_index": index, "declared_fault_adjacency": adjacency[block_id]}
        copied = copy.deepcopy(feature)
        if "tectonic_crosswalk" in copied["properties"]:
            raise SnapshotError("source already contains a tectonic_crosswalk")
        copied["properties"]["tectonic_crosswalk"] = entry
        crosswalk.append(copied)
        motion_blocks.append({"block_id": block_id, "entity_type": "structural_block", **vector,
                              "source_refs": velocity.get("source_refs", []),
                              "status": "UNKNOWN" if vector["speed"] is None else "SUPPLIED_UNVERIFIED"})
    relationships, motion_faults = [], []
    for index, feature in faults:
        props = feature["properties"]
        fault_id = props["fault_id"]
        left, right = props.get("left_block_id"), props.get("right_block_id")
        if left not in motions or right not in motions or left == right:
            raise SnapshotError(f"unresolved or identical declared fault sides: {fault_id}")
        plate_left = block_decisions.get(left, {}).get("plate_id")
        plate_right = block_decisions.get(right, {}).get("plate_id")
        decision = fault_decisions.get(fault_id, {})
        boundary = decision.get("plate_boundary")
        if boundary is True and plate_left is not None and plate_left == plate_right:
            raise SnapshotError(f"plate-boundary claim conflicts with identical plate IDs: {fault_id}")
        relation = {"fault_id": fault_id, "left_block_id": left, "right_block_id": right,
                    "left_plate_id": plate_left, "right_plate_id": plate_right,
                    "plate_boundary": boundary,
                    "boundary_status": "UNKNOWN" if boundary is None else "SUPPLIED_UNVERIFIED",
                    "source_refs": decision.get("source_refs", []), "source_feature_index": index,
                    "sidedness_status": "SOURCE_DECLARATION_NOT_GEOMETRICALLY_REVALIDATED"}
        for owner, neighbour in ((left, right), (right, left)):
            adjacency[owner].append({"fault_id": fault_id, "neighbour_block_id": neighbour,
                                     "basis": "DECLARED_FAULT_SIDES_NOT_SPATIAL_ADJACENCY_AUDIT"})
        copied = copy.deepcopy(feature)
        if "tectonic_relationship" in copied["properties"]:
            raise SnapshotError("source already contains a tectonic_relationship")
        copied["properties"]["tectonic_relationship"] = relation
        relationships.append(copied)
        components = []
        for component in ("vx", "vy"):
            a, b = motions[left][component], motions[right][component]
            components.append(None if a is None or b is None else _number(b - a, "relative velocity"))
        relative = _vector(*components)
        motion_faults.append({"fault_id": fault_id, "left_block_id": left, "right_block_id": right,
                              "relative_velocity_right_minus_left": relative,
                              "segments": _segments(feature["geometry"]["coordinates"], relative),
                              "physical_slip_or_convergence_interpretation": None})
    missing = {"plate_identity_block_ids": [v for v in block_ids if block_decisions.get(v, {}).get("plate_id") is None],
               "complete_motion_block_ids": [v for v in block_ids if motions[v]["speed"] is None],
               "boundary_decision_fault_ids": [v for v in fault_ids if fault_decisions.get(v, {}).get("plate_boundary") is None]}
    validation = {"status": "INCOMPLETE" if any(missing.values()) else "COMPLETE_ENGINEERING_SNAPSHOT",
                  "structural_block_count": len(blocks), "finite_fault_count": len(faults),
                  "missing": missing, "source_claims_independently_verified": False,
                  "geometry_audit_performed": False, "category_complete": False, "production_authorized": False,
                  "required_external_gates": ["independent source/decision authority binding", "geometry audit",
                                              "domain acceptance and full-category coverage"]}
    snapshot = {**copy.deepcopy(common), "snapshot_id": decisions["snapshot_id"] if decisions else "History A / E7 present structural state",
                "snapshot_source_refs": decisions["snapshot_source_refs"] if decisions else [],
                "retained_events": copy.deepcopy(events), "retained_lineage": copy.deepcopy(lineage),
                "temporal_model": "FIXED_SNAPSHOT_NO_EVOLUTION", "velocity_units": UNITS,
                "velocity_reference_frame": decisions["reference_frame"] if decisions else None,
                "bearing_convention": "degrees clockwise from geographic north; null at zero/unknown speed",
                "normal_convention": "right=(-dy,+dx); left=(+dy,-dx), in original trace order",
                "blocks": motion_blocks, "faults": motion_faults, "validation": validation}
    products = {PRODUCT_NAMES[0]: {**copy.deepcopy(common), "type": "FeatureCollection", "features": crosswalk},
                PRODUCT_NAMES[1]: {**copy.deepcopy(common), "type": "FeatureCollection", "features": relationships},
                PRODUCT_NAMES[2]: snapshot}
    for pin in pins:
        if _read(package / pin["file"])[1] != pin:
            raise SnapshotError(f"consumed package input changed during snapshot: {pin['file']}")
    _json_tree(products)
    return {"products": products, "validation": copy.deepcopy(validation)}
