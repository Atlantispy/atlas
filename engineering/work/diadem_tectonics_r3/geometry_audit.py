"""Reconstructed, independent History A geometry checks (not the old auditor).

Reads package products only. No producer imports, output writes, repair, canon
promotion, historical PASS reuse, or visual approval. Coordinates are kilometres.
Floating geometric predicates use 1e-7 km; polygon overlay areas use 1e-6 km2.
These are numerical round-off bounds, not permission to alter stored products.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
from pathlib import Path

try:
    import numpy as np
    from shapely.geometry import Point, LineString, box, shape
    from shapely.ops import unary_union
    from shapely.validation import explain_validity
    DEPENDENCY_ERROR = None
except ImportError as exc:
    DEPENDENCY_ERROR = str(exc)

PREFIX = "checkpoint1-history-a-"
EPS_KM = 1e-7
AREA_EPS_KM2 = 1e-6
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_ISSUES = 120
DOCUMENT_FILES = (("events", "json"), ("faults-blocks", "geojson"),
                  ("accommodation", "geojson"), ("provinces", "geojson"),
                  ("sections", "geojson"))
CODES = (
    "VECTOR_PRIMARY_LAYER_INVENTORY", "NO_UNAPPROVED_EXTERNAL_APRON",
    "STRUCTURAL_DOMAIN_PARTITION_AND_RASTER_SCOPE", "FAULT_GRAPH_SCHEMA_AND_TOPOLOGY",
    "BLOCK_KINEMATIC_DERIVATION", "CROWN_GATE_AND_MASSIF_MODEL",
    "ACCOMMODATION_GRAPH_AND_ARTIFICIAL_ISLAND_DEFERRAL", "STRUCTURALLY_COUPLED_PROVINCES",
    "TRUE_MAP_MATCHED_SECTIONS",
)
ID_KEYS = {
    "fault_segment": "fault_id", "topology_node": "node_id", "structural_block": "block_id",
    "structural_model_domain": "model_domain_id", "crown_system": "crown_system_id",
    "crown_link": "link_id", "massif_shoulder_or_spur": "shoulder_or_spur_id",
    "massif_local_contact": "local_contact_id", "massif_structural_envelope": "massif_id",
    "titan_transfer_component": "component_id", "non_fault_contact": "contact_id",
    "event_domain": "event_domain_id", "accommodation_compartment": "accommodation_id",
    "accommodation_connection": "connection_id", "geological_province": "province_id",
}
GEOMETRY_TYPES = {
    "fault_segment": "LineString", "topology_node": "Point", "structural_block": "Polygon",
    "structural_model_domain": "Polygon", "crown_system": "Polygon", "crown_link": "LineString",
    "massif_shoulder_or_spur": "LineString", "massif_local_contact": "LineString",
    "massif_structural_envelope": "Polygon", "titan_transfer_component": "Polygon",
    "non_fault_contact": "LineString", "event_domain": "Polygon",
    "accommodation_compartment": "Polygon", "accommodation_connection": "LineString",
    "geological_province": "Polygon", "section_trace": "LineString",
    "section_fault_plane": "LineString", "section_contact": "LineString",
    "section_block_interval": "LineString", "section_basement_profile": "LineString",
    "section_accommodation_wedge": "Polygon", "section_structural_body": "Polygon",
}


def _read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"nonfinite JSON number {value}")

    def number(value):
        result = float(value)
        return result if math.isfinite(result) else constant(value)

    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path.name}")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("JSON grew beyond bound")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                       parse_float=number, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


class _DecodedInputs:
    """Single-use bridge from this invocation's strict package JSON reader.

    The package reader rejects duplicate keys, nonfinite numbers and non-object
    roots and has a smaller byte bound. Its BOM acceptance is deliberately NOT
    inherited: retain the geometry reader's BOM and size errors until its turn.
    Nothing is persisted and no previously validated document is accepted here.
    """
    def __init__(self, package):
        self.package = Path(package)
        self.values = {}
        self.used = False

    def _capture(self, path, raw, value, stat_size):
        path = Path(path)
        if self.used or path.parent != self.package or path.name in self.values:
            raise ValueError("Geometry input invocation/path/uniqueness mismatch")
        error = None
        if stat_size > MAX_JSON_BYTES:
            error = ValueError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path.name}")
        elif len(raw) > MAX_JSON_BYTES:
            error = ValueError("JSON grew beyond bound")
        elif raw.startswith(b"\xef\xbb\xbf"):
            # Reproduce json.loads(utf-8 decoded text)'s original error exactly.
            error = json.JSONDecodeError("Unexpected UTF-8 BOM (decode using utf-8-sig)", "\ufeff", 0)
        elif not isinstance(value, dict):
            error = ValueError("expected JSON object")
        self.values[path.name] = (value, error)

    def _take(self, package):
        if self.used or Path(package) != self.package:
            raise ValueError("Geometry inputs belong to one exact audit invocation")
        self.used = True
        def take(name):
            value, error = self.values[name]
            if error is not None:
                raise error
            return value
        documents = {name: take(f"{PREFIX}{name}.{extension}")
                     for name, extension in DOCUMENT_FILES}
        checkpoint = take("checkpoint0-frozen-inputs.json")
        self.values.clear()
        return documents, checkpoint


def _bounds_may_meet(left, right):
    """Conservative candidate only; exact predicates still decide every hit.

    Outward nextafter protects an EPS expansion which rounds inward at the
    boundary. Even diagonal false positives are retained. Order is untouched.
    """
    return not (math.nextafter(left[2] + EPS_KM, math.inf) < right[0] or
                math.nextafter(right[2] + EPS_KM, math.inf) < left[0] or
                math.nextafter(left[3] + EPS_KM, math.inf) < right[1] or
                math.nextafter(right[3] + EPS_KM, math.inf) < left[1])


def _coordinates(value):
    if (isinstance(value, list) and len(value) == 2 and
            all(type(v) in (int, float) and math.isfinite(v) for v in value)):
        yield tuple(value)
    elif isinstance(value, list):
        for item in value:
            yield from _coordinates(item)
    else:
        raise ValueError("geometry coordinates must be finite 2D positions")


def _unique_strings(value):
    return (isinstance(value, list) and all(isinstance(x, str) and x for x in value)
            and len(value) == len(set(value)))


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _point_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [geometry]
    if geometry.geom_type in ("MultiPoint", "GeometryCollection"):
        result = []
        for child in geometry.geoms:
            result.extend(_point_parts(child))
        return result
    raise ValueError(f"non-point line intersection: {geometry.geom_type}")


class Context:
    """Small vector-only context, also constructible from synthetic documents."""
    def __init__(self, documents, checkpoint, contract, arrays=None):
        self.documents, self.checkpoint, self.contract = documents, checkpoint, contract
        self.arrays = arrays
        self.layers = defaultdict(list)
        self.plan = []
        self.sections = []
        self.by_id = {}
        self.geometry = {}
        self._bounds = {}
        self._groups = {}
        self._centroids = {}
        self._section_groups = None
        self.problems = []
        self.events = {e["event_id"] for e in documents["events"]["events"]}
        for source in ("faults-blocks", "accommodation", "provinces", "sections"):
            document = documents[source]
            if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
                raise ValueError(f"{source}: expected FeatureCollection")
            for index, feature in enumerate(document["features"]):
                label = f"{source}[{index}]"
                if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
                    raise ValueError(f"{label}: invalid feature")
                properties = feature["properties"]
                layer = properties.get("layer")
                if not isinstance(layer, str):
                    raise ValueError(f"{label}: missing layer")
                self.layers[layer].append(feature)
                (self.sections if source == "sections" else self.plan).append(feature)
                identity = properties.get(ID_KEYS.get(layer, ""), label)
                if layer in ID_KEYS:
                    if not isinstance(identity, str) or not identity:
                        self.problems.append(f"{label}: missing valid identifier")
                    elif identity in self.by_id:
                        self.problems.append(f"duplicate feature identifier: {identity}")
                    else:
                        self.by_id[identity] = feature
                try:
                    raw_geometry = feature["geometry"]
                    coords = list(_coordinates(raw_geometry["coordinates"]))
                    if raw_geometry["type"] == "Polygon":
                        rings = raw_geometry["coordinates"]
                        if (not rings or any(not isinstance(ring, list) or len(ring) < 4 or
                                             ring[0] != ring[-1] for ring in rings)):
                            raise ValueError("GeoJSON polygon rings must be explicitly closed")
                    geom = shape(raw_geometry)
                    expected_type = GEOMETRY_TYPES.get(layer)
                    if not coords or geom.is_empty or not geom.is_valid:
                        raise ValueError(explain_validity(geom))
                    if expected_type is None or geom.geom_type != expected_type:
                        raise ValueError(f"unexpected {geom.geom_type} for {layer}")
                    if geom.geom_type == "LineString" and (geom.length <= 0 or not geom.is_simple):
                        raise ValueError("degenerate or self-intersecting line")
                    if geom.geom_type == "Polygon" and geom.area <= 0:
                        raise ValueError("non-positive polygon area")
                    self.geometry[id(feature)] = geom
                except Exception as exc:
                    self.problems.append(f"{identity}: invalid geometry: {exc}")

    def geom(self, feature):
        return self.geometry[id(feature)]

    def group(self, layer):
        if layer not in self._groups:
            self._groups[layer] = {f["properties"][ID_KEYS[layer]]: f for f in self.layers[layer]}
        return self._groups[layer]

    def bounds(self, feature):
        key = id(feature)
        if key not in self._bounds:
            self._bounds[key] = self.geom(feature).bounds
        return self._bounds[key]

    def centroid(self, feature):
        key = id(feature)
        if key not in self._centroids:
            self._centroids[key] = self.geom(feature).centroid
        return self._centroids[key]

    def section_entries(self, sid):
        if self._section_groups is None:
            groups = defaultdict(list)
            for feature in self.sections:
                key = feature["properties"].get("section_id")
                # A JSON array/object cannot equal a valid hashable trace ID.
                # Keep those malformed IDs for the original final unknown check.
                if not isinstance(key, (list, dict)):
                    groups[key].append(feature)
            self._section_groups = groups
        return self._section_groups[sid]

    def check_properties(self, layer, required, issues):
        for feature in self.layers[layer]:
            p = feature["properties"]
            missing = sorted(set(required) - set(p))
            if missing:
                issues.append(f"{p.get(ID_KEYS.get(layer, ''), layer)} missing properties {missing}")

    def check_events(self, properties, keys, label, issues):
        for key in keys:
            value = properties[key]
            values = value if isinstance(value, list) else [value]
            if not _unique_strings(values) or any(v not in self.events for v in values):
                issues.append(f"{label}: invalid event references in {key}")


def _result(code, summary, issues, metrics=None):
    return {"code": code, "status": "FAIL" if issues else "PASS", "summary": summary,
            "metrics": {"reconstructed_independent_check": True,
                        "historical_auditor_reexecuted": False,
                        "issue_count": len(issues), "issues": issues[:MAX_ISSUES],
                        "issues_truncated": len(issues) > MAX_ISSUES, **(metrics or {})},
            "evidence": ["checkpoint1-event-model-audit-contract-review-only.json",
                         "checkpoint0-frozen-inputs.json", "package vector features; independently measured"]}


def _inventory(c):
    issues = list(c.problems)
    observed = set(f["properties"]["layer"] for f in c.documents["faults-blocks"]["features"])
    required = set(c.contract["faults_blocks_layers"]["required"])
    allowed = required | set(c.contract["faults_blocks_layers"].get("optional", []))
    if required - observed:
        issues.append(f"missing primary layers: {sorted(required-observed)}")
    if observed - allowed:
        issues.append(f"unexpected primary layers: {sorted(observed-allowed)}")
    return _result(CODES[0], "Required vector layers, unique identifiers and finite valid geometries.", issues,
                   {"observed_layer_counts": {k: len(v) for k, v in sorted(c.layers.items())}})


def _frame(c):
    cr = c.checkpoint["coordinate_reference"]
    if cr["horizontal_unit"] != "km" or cr["x_direction"] != "east" or cr["y_direction"] != "south":
        raise ValueError("unrecognised frozen coordinate reference")
    return box(0, 0, cr["public_frame_width"]["value"], cr["public_frame_height"]["value"])


def _apron(c):
    issues, frame = [], _frame(c)
    plan_features = c.plan + c.layers["section_trace"]
    for feature in plan_features:
        geom = c.geom(feature)
        if not frame.covers(geom):
            p = feature["properties"]
            issues.append(f"outside public frame: {p.get(ID_KEYS.get(p['layer'], ''), p.get('section_id'))}")
    return _result(CODES[1], "All plan geometry stays within the frozen public frame; section depth is not a plan coordinate.",
                   issues, {"plan_feature_count": len(plan_features), "frame_bounds_km": list(frame.bounds)})


def _partition(c):
    issues = []
    required = c.contract["structural_model_domain_contract"]
    domains = c.layers["structural_model_domain"]
    c.check_properties("structural_model_domain", c.contract["required_structural_model_domain_properties"], issues)
    if len(domains) != required["required_feature_count"]:
        raise ValueError("expected exactly one structural model domain")
    domain, p = c.geom(domains[0]), domains[0]["properties"]
    blocks = c.group("structural_block")
    if p["model_domain_id"] != required["required_model_domain_id"]:
        issues.append("model domain identifier differs")
    if not _unique_strings(p["included_block_ids"]) or set(p["included_block_ids"]) != set(blocks):
        issues.append("declared domain block inventory differs")
    if type(p["outside_raster_sentinel"]) is not int or p["outside_raster_sentinel"] != required["outside_raster_sentinel"]:
        issues.append("declared outside sentinel differs")
    c.check_events(p, ["event_ids"], p["model_domain_id"], issues)
    union = unary_union([c.geom(f) for f in blocks.values()])
    gap = domain.difference(union).area
    outside = union.difference(domain).area
    overlap = sum(c.geom(f).area for f in blocks.values()) - union.area
    if gap > AREA_EPS_KM2 or outside > AREA_EPS_KM2 or overlap > AREA_EPS_KM2:
        issues.append(f"block partition mismatch: gap={gap}, outside={outside}, overlap={overlap} km2")
    frame_area = _frame(c).area
    if required["whole_public_frame_tiling_forbidden"] and domain.area >= frame_area - AREA_EPS_KM2:
        issues.append("domain tiles the whole public frame")
    budget = c.checkpoint["area_budget"]["inner_watershed"]
    if not budget["minimum"] <= domain.area <= budget["maximum"]:
        issues.append("domain area is outside approved working range")
    return _result(CODES[2], "Vector blocks partition the inner structural domain without overlap or external quilt.", issues,
                   {"domain_area_km2": domain.area, "block_union_area_km2": union.area,
                    "gap_area_km2": gap, "outside_area_km2": outside, "overlap_area_km2": overlap,
                    "polygon_area_roundoff_bound_km2": AREA_EPS_KM2,
                    "raster_part_checked_here": False, "requires_aggregator_raster_checks": True})


def _fault_graph(c):
    issues, relay_terminals = [], []
    faults, nodes = c.group("fault_segment"), c.group("topology_node")
    blocks = c.group("structural_block")
    c.check_properties("fault_segment", c.contract["required_fault_properties"], issues)
    incident = defaultdict(set)
    for fid, feature in faults.items():
        p, geom = feature["properties"], c.geom(feature)
        c.check_events(p, ["event_created", "events_reactivated"], fid, issues)
        if p["alternative"] != "A":
            issues.append(f"{fid}: wrong history")
        for side in ("left_block_id", "right_block_id"):
            if p[side] not in blocks:
                issues.append(f"{fid}: unresolved {side}")
        dip = p["dip_range_deg"]
        if not isinstance(dip, list) or len(dip) != 2 or not all(_number(v) for v in dip) or not 0 < dip[0] <= dip[1] <= 90:
            issues.append(f"{fid}: invalid dip range")
        related = p.get("related_segment_ids", [])
        if not _unique_strings(related) or any(x not in c.by_id for x in related):
            issues.append(f"{fid}: unresolved related structure")
        for edge, coordinate in (("start", geom.coords[0]), ("end", geom.coords[-1])):
            nid = p[f"{edge}_node_id"]
            incident[nid].add(fid)
            if nid not in nodes:
                issues.append(f"{fid}: missing {edge} node {nid}")
                continue
            node = nodes[nid]
            if Point(coordinate).distance(c.geom(node)) > EPS_KM:
                issues.append(f"{fid}: {edge} endpoint does not match node {nid}")
            if p.get(f"{edge}_termination_type") != node["properties"]["node_type"]:
                issues.append(f"{fid}: {edge} termination type differs from node")
        expected_target = f"{p['start_node_id']}|{p['end_node_id']}"
        if p["termination_type"] != "finite_between_recorded_nodes" or p["termination_target_id"] != expected_target:
            issues.append(f"{fid}: unresolved finite termination target")
    terminal_types = {"tip_termination", "buried_continuation", "Gate_margin_termination", "abutment"}
    for nid, node in nodes.items():
        p = node["properties"]
        declared = p.get("incident_fault_ids")
        node_bounds = c.bounds(node)
        actual = {fid for fid, fault in faults.items()
                  if _bounds_may_meet(node_bounds, c.bounds(fault)) and
                  c.geom(node).distance(c.geom(fault)) <= EPS_KM}
        incident[nid] = actual
        if not _unique_strings(declared) or set(declared) != actual or not actual:
            issues.append(f"{nid}: node/fault incidence mismatch")
        nt = p.get("node_type")
        if nt not in c.contract["allowed_node_types"] or not p.get("event_relation"):
            issues.append(f"{nid}: invalid node type or missing relation")
        degree = sum(1 if min(c.geom(node).distance(Point(c.geom(faults[fid]).coords[i]))
                              for i in (0, -1)) <= EPS_KM else 2 for fid in actual)
        if degree >= 4 and nt != "crossing_with_age_relation":
            issues.append(f"{nid}: high-degree crossing lacks age relation")
        if nt == "crossing_with_age_relation":
            ages = {faults[fid]["properties"]["event_created"] for fid in actual}
            relation = p.get("event_relation", "")
            if len(ages) < 2 or not all(age in relation for age in ages):
                issues.append(f"{nid}: crossing does not explicitly identify distinct source events")
        if len(actual) == 1 and nt not in terminal_types:
            fid = next(iter(actual))
            fp = faults[fid]["properties"]
            partners = [x for x in fp.get("related_segment_ids", []) if x in faults and
                        fp.get("relay_pair_id_or_null") and
                        faults[x]["properties"].get("relay_pair_id_or_null") == fp["relay_pair_id_or_null"] and
                        fid in faults[x]["properties"].get("related_segment_ids", [])]
            if nt in {"relay_entry", "relay_exit"} and partners:
                relay_terminals.append({"node": nid, "fault": fid, "partners": partners})
            else:
                issues.append(f"{nid}: unresolved degree-one {nt}")
    # A pair's geometric crossing is not inferred from a shared relation string.
    # It needs a real common graph node at the crossing location, or an explicit
    # crossing-with-age-relation node incident to both segments.
    unresolved_crossings = []
    ids = sorted(faults)
    for i, left in enumerate(ids):
        for right in ids[i+1:]:
            if not _bounds_may_meet(c.bounds(faults[left]), c.bounds(faults[right])):
                continue
            intersection = c.geom(faults[left]).intersection(c.geom(faults[right]))
            if intersection.is_empty:
                continue
            try:
                positions = _point_parts(intersection)
            except ValueError:
                unresolved_crossings.append({"faults": [left, right], "kind": intersection.geom_type})
                continue
            for position in positions:
                matches = [nid for nid, fids in incident.items() if {left, right} <= fids and
                           nid in nodes and position.distance(c.geom(nodes[nid])) <= EPS_KM]
                if not matches:
                    lp, rp = faults[left]["properties"], faults[right]["properties"]
                    unresolved_crossings.append({"faults": [left, right], "xy_km": [position.x, position.y],
                        "created_events": [lp["event_created"], rp["event_created"]],
                        "shared_relay_id": lp.get("relay_pair_id_or_null") if
                            lp.get("relay_pair_id_or_null") == rp.get("relay_pair_id_or_null") else None,
                        "mutually_related": right in lp.get("related_segment_ids", []) and
                                             left in rp.get("related_segment_ids", []),
                        "interpretation": "Plan traces cross; connected-junction versus age-separated crossing is not established by a colocated node/event-relation record."})
    if unresolved_crossings:
        issues.append(f"{len(unresolved_crossings)} geometric fault crossings lack an explicit colocated graph node")
    types = Counter(n["properties"]["node_type"] for n in nodes.values())
    if not ({"branch", "transfer", "relay_entry", "relay_exit"} <= set(types)):
        issues.append("finite graph lacks required branch/relay/transfer variety")
    return _result(CODES[3], "Finite fault/node schema, endpoint incidence, relay exceptions and actual geometric crossings.", issues,
                   {"fault_count": len(faults), "node_count": len(nodes), "node_types": dict(types),
                    "valid_degree_one_relay_terminals": relay_terminals,
                    "unresolved_geometric_crossings": unresolved_crossings,
                    "crossing_connectivity_inferred": False,
                    "endpoint_roundoff_bound_km": EPS_KM})


def _measure_block_edges(c, blocks):
    """Measure only internal boundaries against each block's declared sources.

    The model-domain perimeter is an allowed event-envelope boundary, excluded
    from this test. Unsupported pieces are *unresolved boundary provenance*, not
    an assertion that those pieces must be physical faults rather than contacts.
    Shared internal edges occur twice in per-block lengths; the unique total
    below is a geometric union and is not double-counted.
    """
    domains = c.layers["structural_model_domain"]
    if len(domains) != 1:
        raise ValueError("one structural domain required for boundary derivation")
    external = c.geom(domains[0]).boundary.buffer(EPS_KM)
    rows, all_source_ids = {}, set()
    for bid, feature in blocks.items():
        p = feature["properties"]
        internal = c.geom(feature).boundary.difference(external)
        source_ids = p["bounding_fault_ids"] + p["non_fault_contact_ids"]
        all_source_ids.update(source_ids)
        source_lines = [c.geom(c.by_id[fid]) for fid in source_ids if fid in c.by_id]
        support = unary_union(source_lines).buffer(EPS_KM)
        unsupported = internal.difference(support)
        pieces = list(unsupported.geoms) if hasattr(unsupported, "geoms") else [unsupported]
        rows[bid] = {"internal_boundary_length_km": internal.length,
                     "unsupported_internal_length_km": unsupported.length,
                     "declared_boundary_source_ids": source_ids,
                     "unsupported_segment_examples": [list(map(list, part.coords)) for part in pieces[:6]
                                                       if not part.is_empty and part.geom_type == "LineString"]}
    # Union original boundaries BEFORE clipping. Independently clipped shared
    # endpoints may differ by floating round-off and otherwise double-count a
    # coincident edge. The unique total is coverage against ANY declared source;
    # each block's own source association remains separately measured above.
    unique_internal = unary_union([c.geom(f).boundary for f in blocks.values()]).difference(external)
    any_source = unary_union([c.geom(c.by_id[fid]) for fid in all_source_ids if fid in c.by_id]).buffer(EPS_KM)
    unique_unsupported = unique_internal.difference(any_source)
    return {"per_block": rows, "unique_internal_boundary_length_km": unique_internal.length,
            "unique_unsupported_internal_boundary_length_km": unique_unsupported.length,
            "unique_total_support_scope": "any declared boundary source; individual block/source association is checked per block",
            "domain_perimeter_excluded": True, "geometry_roundoff_bound_km": EPS_KM,
            "interpretation": "Unresolved internal-edge provenance; a missing source may be a fault, a non-fault contact or another explicitly justified structural boundary. No physical fault is inferred."}


def _blocks(c):
    issues = []
    blocks, faults = c.group("structural_block"), c.group("fault_segment")
    contacts = c.group("non_fault_contact")
    c.check_properties("structural_block", c.contract["required_block_properties"], issues)
    masters = {f["properties"]["master_domain_id"] for f in blocks.values()}
    required = set(c.contract["required_master_domain_ids"]["a"])
    allowed = set(c.contract["allowed_master_domain_ids"]["a"])
    if not required <= masters or not masters <= allowed:
        issues.append("master-domain inventory differs")
    if len(blocks) > c.contract["hard_thresholds"]["maximum_master_domain_block_count"]:
        issues.append("block count exceeds maximum")
    quadrilaterals = 0
    for bid, feature in blocks.items():
        p, geom = feature["properties"], c.geom(feature)
        quadrilaterals += len(geom.exterior.coords) - 1 == 4
        c.check_events(p, ["event_formed", "events_modified"], bid, issues)
        for key, lookup in (("bounding_fault_ids", faults), ("non_fault_contact_ids", contacts)):
            if not _unique_strings(p[key]) or any(x not in lookup for x in p[key]):
                issues.append(f"{bid}: unresolved {key}")
        if not p["bounding_fault_ids"] and not p["non_fault_contact_ids"]:
            issues.append(f"{bid}: no named boundary derivation")
        rank = p["relative_vertical_rank"]
        if not _number(rank) or p["relative_vertical_state"] != ("positive" if rank > 0 else "negative" if rank < 0 else "neutral"):
            issues.append(f"{bid}: incoherent rank/state")
        if not _number(p["tilt_azimuth_deg"]) or not 0 <= p["tilt_azimuth_deg"] < 360:
            issues.append(f"{bid}: invalid tilt azimuth")
        tilt = p["tilt_controlling_fault_id"]
        if (p["tilt_class"] != "negligible" and tilt not in p["bounding_fault_ids"]) or (tilt is not None and tilt not in faults):
            issues.append(f"{bid}: unresolved tilt controller")
        for fid in p["bounding_fault_ids"]:
            if fid in faults and bid not in {faults[fid]["properties"]["left_block_id"], faults[fid]["properties"]["right_block_id"]}:
                issues.append(f"{bid}/{fid}: nonreciprocal block/fault reference")
    fraction = quadrilaterals / len(blocks) if blocks else 1.0
    if fraction > c.contract["hard_thresholds"]["maximum_quadrilateral_block_fraction"]:
        issues.append("too many quadrilateral blocks")
    nonbounding_side_associations = []
    for fid, feature in faults.items():
        p = feature["properties"]
        for bid in {p["left_block_id"], p["right_block_id"]}:
            if bid not in blocks or fid not in blocks[bid]["properties"]["bounding_fault_ids"]:
                # Left/right regional block context does not assert that an
                # interior fracture/relay bounds that block. Reciprocity is
                # required for the explicit block.bounding_fault_ids above.
                nonbounding_side_associations.append([fid, bid])
        down, up = p["downthrown_block_id_or_null"], p["upthrown_block_id_or_null"]
        if p["kinematic_class"] in {"normal", "oblique_normal"}:
            if down not in blocks or up not in blocks or {down, up} != {p["left_block_id"], p["right_block_id"]}:
                issues.append(f"{fid}: unresolved normal-fault polarity")
            elif blocks[down]["properties"]["relative_vertical_rank"] >= blocks[up]["properties"]["relative_vertical_rank"]:
                issues.append(f"{fid}: downthrown rank not below upthrown rank")
        elif p["kinematic_class"] == "transfer":
            if down is not None or up is not None or not p["shear_sense_or_null"]:
                issues.append(f"{fid}: invalid transfer shear/polarity")
        elif p["kinematic_class"] == "fracture":
            if down is not None or up is not None:
                issues.append(f"{fid}: fracture invents throw polarity")
        else:
            issues.append(f"{fid}: unknown kinematic class")
    named_issues = list(issues)
    edges = _measure_block_edges(c, blocks)
    if any(row["unsupported_internal_length_km"] > EPS_KM for row in edges["per_block"].values()):
        issues.append("Internal block-edge derivation is unresolved against declared fault/contact sources: "
                      f"{edges['unique_unsupported_internal_boundary_length_km']} km (domain perimeter excluded)")
    return _result(CODES[4], "Named block/fault references, rank polarity, tilt controls and internal-boundary source coverage.", issues,
                   {"block_count": len(blocks), "quadrilateral_block_fraction": fraction,
                    "named_reference_and_kinematic_issues": named_issues,
                    "internal_boundary_derivation": edges,
                    "regional_side_associations_not_declared_as_boundaries": sorted(nonbounding_side_associations),
                    "polygon_edges_reconstructed_from_faults": False})


def _ellipse_irregularity(positions):
    """Independent axis-aligned algebraic fit; diagnostic, never a field input."""
    xy = np.asarray(positions, dtype=np.float64)
    if xy.ndim != 2 or xy.shape[1] != 2 or len(xy) < 5:
        raise ValueError("ellipse diagnostic needs at least five 2D positions")
    offset, scale = xy.mean(axis=0), xy.std(axis=0)
    if np.any(scale == 0):
        raise ValueError("degenerate ellipse diagnostic input")
    uv = (xy - offset) / scale
    u, v = uv.T
    coefficients, _, rank, _ = np.linalg.lstsq(np.column_stack((u*u, v*v, u, v)),
                                             np.ones(len(xy)), rcond=None)
    a, b, d, e = coefficients
    if rank != 4 or a <= 0 or b <= 0:
        raise ValueError("algebraic fit is not a bounded ellipse")
    centre = np.asarray([-d / (2*a), -e / (2*b)])
    factor = 1 + d*d/(4*a) + e*e/(4*b)
    axes = np.sqrt(factor / np.asarray([a, b]))
    q = np.sqrt(np.sum(((uv-centre)/axes)**2, axis=1))
    return {"q_std": float(q.std()), "q_mean": float(q.mean()),
            "centre_km": (offset + centre*scale).tolist(), "semi_axes_km": (axes*scale).tolist(),
            "method": "independent centred/scaled axis-aligned algebraic least-squares fit"}


def _crown(c):
    issues = []
    crowns, links = c.group("crown_system"), c.group("crown_link")
    massifs, shoulders = c.group("massif_structural_envelope"), c.group("massif_shoulder_or_spur")
    contacts, titan = c.group("massif_local_contact"), c.group("titan_transfer_component")
    faults = c.group("fault_segment")
    if set(crowns) != set(c.contract["required_crown_system_ids"]):
        issues.append("Crown system inventory differs")
    if set(titan) != set(c.contract["required_titan_component_ids"]):
        issues.append("Titan transfer-component inventory differs")
    frame = _frame(c)
    for tid, feature in titan.items():
        centre = c.centroid(feature)
        if not (centre.x > frame.bounds[2]/2 and centre.y < frame.bounds[3]/2):
            issues.append(f"{tid}: Gate component is not in the north-east frame quadrant")
        c.check_events(feature["properties"], ["event_ids"], tid, issues)
    e1 = {fid for fid, f in faults.items() if f["properties"]["event_created"] == "E1"}
    all_members = []
    for cid, feature in crowns.items():
        p = feature["properties"]
        members = p["member_fault_ids"]
        if not _unique_strings(members) or not members:
            issues.append(f"{cid}: invalid member fault list")
        all_members.extend(members)
        c.check_events(p, ["event_ids"], cid, issues)
        for fid in members:
            if (fid not in faults or fid not in e1 or faults[fid]["properties"]["family_id"] != cid or
                    faults[fid]["properties"].get("parent_crown_system_id_or_null") != cid):
                issues.append(f"{cid}/{fid}: invalid E1 Crown membership")
    if set(all_members) != e1 or len(all_members) != len(set(all_members)):
        issues.append("Crown memberships do not uniquely cover all E1 segments")
    c.check_properties("crown_link", c.contract["required_crown_link_properties"], issues)
    c.check_properties("massif_structural_envelope", c.contract["required_massif_properties"], issues)
    anchors = {a["haus"]: Point(a["x"], a["y"]) for a in c.checkpoint["peak_anchors"]["anchors"]}
    order = c.checkpoint["peak_anchors"]["clockwise_order_from_north_west_gate_flank"]
    if not _unique_strings(order) or set(order) != set(anchors):
        raise ValueError("invalid frozen anchor order")
    expected_links = {frozenset((a, b)) for a, b in zip(order, order[1:] + order[:1])}
    expected_links.remove(frozenset(("edelstein", "glanzgrund")))
    actual_links = []
    normalized_shapes = defaultdict(list)
    for lid, feature in links.items():
        p, geom = feature["properties"], c.geom(feature)
        pair = frozenset((p["from_haus"], p["to_haus"]))
        actual_links.append(pair)
        if len(pair) != 2 or not pair <= set(anchors):
            issues.append(f"{lid}: invalid massif relationship")
        if not _unique_strings(p["parent_crown_system_ids"]) or not p["parent_crown_system_ids"] or not set(p["parent_crown_system_ids"]) <= set(crowns):
            issues.append(f"{lid}: unresolved parent Crown systems")
        c.check_events(p, ["event_ids"], lid, issues)
        if not p["saddle_or_transfer_id"]:
            issues.append(f"{lid}: missing saddle/transfer identity")
        coords = np.asarray(geom.coords)
        origin, delta = coords[0], coords[-1]-coords[0]
        length = float(np.linalg.norm(delta))
        if length <= EPS_KM:
            issues.append(f"{lid}: closed/degenerate relationship mark")
        else:
            unit = delta/length
            normal = np.asarray([-unit[1], unit[0]])
            normalized = np.column_stack(((coords-origin)@unit/length, (coords-origin)@normal/length))
            normalized_shapes[tuple(np.round(normalized, 10).flat)].append(lid)
    if set(actual_links) != expected_links or len(actual_links) != len(expected_links):
        issues.append("Crown relationships differ from 19 ordered neighbours with the sole Gate gap")
    repeated = [ids for ids in normalized_shapes.values() if len(ids) > 1]
    if repeated:
        issues.append("repeated normalized Crown-link geometry")
    by_haus = {}
    for mid, feature in massifs.items():
        haus = feature["properties"]["haus"]
        if haus in by_haus:
            issues.append(f"duplicate massif for {haus}")
        by_haus[haus] = feature
    if set(by_haus) != set(anchors) or len(massifs) != len(anchors):
        issues.append("massifs do not correspond one-to-one with frozen references")
    if len(shoulders) != len(anchors) or len(contacts) != len(anchors):
        issues.append("missing one-per-massif shoulder/contact support")
    distances, centroids = {}, []
    for mid, feature in massifs.items():
        p, geom = feature["properties"], c.geom(feature)
        haus = p["haus"]
        if haus not in anchors:
            continue
        c.check_events(p, ["event_ids"], mid, issues)
        if not geom.covers(anchors[haus]):
            issues.append(f"{mid}/{haus}: reference is outside its massif")
        centre = c.centroid(feature)
        distance = anchors[haus].distance(centre)
        distances[haus] = distance
        centroids.append([centre.x, centre.y])
        if distance < c.contract["hard_thresholds"]["minimum_reference_to_massif_centroid_distance_km"]:
            issues.append(f"{mid}: massif centroid is an anchor control")
        parent = p["parent_crown_segment_ids"]
        support_ids = [p["shoulder_or_spur_id"], *p["local_contact_ids"], *parent, *p["related_structure_ids"]]
        if (not _unique_strings(parent) or not parent or not set(parent) <= e1 or
                p["shoulder_or_spur_id"] not in shoulders or not p["local_contact_ids"] or
                not set(p["local_contact_ids"]) <= set(contacts)):
            issues.append(f"{mid}: missing finite Crown/shoulder/contact support")
        if (not _unique_strings(p["source_feature_ids"]) or
                set(p["source_feature_ids"]) != set(support_ids) or not set(support_ids) <= set(c.by_id)):
            issues.append(f"{mid}: unresolved or incomplete support provenance")
        if not isinstance(p["construction_method"], str) or not p["construction_method"]:
            issues.append(f"{mid}: missing construction method")
        for fid in parent:
            if fid in faults and geom.distance(c.geom(faults[fid])) > EPS_KM:
                issues.append(f"{mid}/{fid}: massif does not touch named parent segment")
        for sid in [p["shoulder_or_spur_id"], *p["local_contact_ids"]]:
            if sid not in c.by_id:
                continue
            sp = c.by_id[sid]["properties"]
            if (sp["haus"] != haus or set(sp["parent_crown_segment_ids"]) != set(parent) or
                    not c.geom(c.by_id[sid]).intersects(geom)):
                issues.append(f"{mid}/{sid}: unrelated or spatially detached support")
            c.check_events(sp, ["event_ids"], sid, issues)
        if "touch_point_km" in p:
            point = Point(p["touch_point_km"])
            if point.distance(geom.boundary) > EPS_KM or not any(point.distance(c.geom(faults[fid])) <= EPS_KM for fid in parent if fid in faults):
                issues.append(f"{mid}: declared touch point does not match parent and massif boundary")
    vertices = [xy for f in c.plan for xy in _coordinates(f["geometry"]["coordinates"])]
    coordinates = np.asarray(vertices, dtype=float)
    near = []
    for haus, anchor in anchors.items():
        distance = float(np.sqrt(np.sum((coordinates-[anchor.x, anchor.y])**2, axis=1)).min())
        if distance < c.contract["hard_thresholds"]["minimum_reference_to_physical_vertex_distance_km"]:
            near.append({"haus": haus, "distance_km": distance})
    if near:
        issues.append("physical vertices are too close to approved reference controls")
    crown_points = [xy for fid in sorted(e1) for xy in c.geom(faults[fid]).coords]
    massif_fit, crown_fit = _ellipse_irregularity(centroids), _ellipse_irregularity(crown_points)
    if massif_fit["q_std"] < c.contract["hard_thresholds"]["minimum_massif_centroid_best_fit_q_std"]:
        issues.append("massif centroids fail ellipse-irregularity threshold")
    if crown_fit["q_std"] < c.contract["hard_thresholds"]["minimum_crown_trace_best_fit_q_std"]:
        issues.append("Crown traces fail ellipse-irregularity threshold")
    return _result(CODES[5], "Crown membership, 19 relationships, NNE Gate, twenty supported containment envelopes and independent anti-anchor diagnostics.",
                   issues, {"crown_count": len(crowns), "link_count": len(links), "massif_count": len(massifs),
                            "reference_centroid_distances_km": distances, "near_reference_vertices": near,
                            "massif_centroid_fit": massif_fit, "crown_trace_fit": crown_fit,
                            "repeated_normalized_link_shapes": repeated,
                            "sole_low_elevation_breach_proven": False,
                            "limit": "Structural Gate uniqueness is checked; no terrain elevations or hydraulic outlet proof exist at this checkpoint."})


def _accommodation(c):
    issues = []
    compartments, connections = c.group("accommodation_compartment"), c.group("accommodation_connection")
    blocks, faults = c.group("structural_block"), c.group("fault_segment")
    missing_layers = set(c.contract["required_accommodation_layers"]) - set(c.layers)
    if missing_layers:
        issues.append(f"missing accommodation layers: {sorted(missing_layers)}")
    if set(compartments) != set(c.contract["required_accommodation_ids"]["a"]):
        issues.append("accommodation compartment inventory differs")
    c.check_properties("accommodation_compartment", c.contract["required_accommodation_compartment_properties"], issues)
    for aid, feature in compartments.items():
        p, geom = feature["properties"], c.geom(feature)
        c.check_events(p, ["event_ids"], aid, issues)
        if (not _unique_strings(p["block_ids"]) or not p["block_ids"] or not set(p["block_ids"]) <= set(blocks) or
                not _unique_strings(p["bounding_fault_ids"]) or not p["bounding_fault_ids"] or
                not set(p["bounding_fault_ids"]) <= set(faults)):
            issues.append(f"{aid}: unresolved blocks/faults")
            continue
        union = unary_union([c.geom(blocks[bid]) for bid in p["block_ids"]])
        if geom.difference(union).area > AREA_EPS_KM2:
            issues.append(f"{aid}: compartment extends outside named blocks")
        if not _number(p["relative_vertical_rank"]) or p["relative_vertical_rank"] >= 0:
            issues.append(f"{aid}: accommodation rank is not subsided")
        for bid in p["block_ids"]:
            bp = blocks[bid]["properties"]
            if bp["accommodation_id_or_null"] != aid or bp["relative_vertical_rank"] != p["relative_vertical_rank"]:
                issues.append(f"{aid}/{bid}: nonreciprocal rank/accommodation mapping")
    for bid, feature in blocks.items():
        aid = feature["properties"]["accommodation_id_or_null"]
        if aid is not None and (aid not in compartments or bid not in compartments[aid]["properties"]["block_ids"]):
            issues.append(f"{bid}: unresolved accommodation mapping")
    edges, adjacency = [], defaultdict(set)
    for lid, feature in connections.items():
        p, line = feature["properties"], c.geom(feature)
        start, end = p["from_id"], p["to_id"]
        c.check_events(p, ["event_ids"], lid, issues)
        edge = frozenset((start, end))
        edges.append(edge)
        if len(edge) != 2 or not edge <= set(compartments):
            issues.append(f"{lid}: invalid connection endpoints")
            continue
        if (Point(line.coords[0]).distance(c.geom(compartments[start])) > EPS_KM or
                Point(line.coords[-1]).distance(c.geom(compartments[end])) > EPS_KM):
            issues.append(f"{lid}: connection geometry misses named compartments")
        adjacency[start].add(end)
        adjacency[end].add(start)
    required_edges = {frozenset(pair) for pair in c.contract["required_accommodation_edges"]["a"]}
    if not required_edges <= set(edges) or len(edges) != len(set(edges)):
        issues.append("required accommodation connections missing or duplicated")
    reached, pending = set(), [next(iter(compartments))] if compartments else []
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(adjacency[node] - reached)
    if reached != set(compartments):
        issues.append("accommodation graph is disconnected")
    policy = c.contract["artificial_island_policy"]
    forbidden_ids, forbidden_layers = set(policy["forbidden_physical_feature_ids"]), set(policy["forbidden_layers"])
    if forbidden_ids & set(c.by_id) or forbidden_layers & set(c.layers):
        issues.append("forbidden natural/artificial-island foundation is modelled")
    if policy["checkpoint1_requirement"] != "deferred_not_modelled_not_scored":
        issues.append("artificial-island deferral policy differs")
    array_names = list(c.arrays.keys()) if c.arrays is not None else []
    forbidden_arrays = [name for name in array_names if any(token.lower() in name.lower()
                        for token in [*forbidden_ids, *forbidden_layers, "natural_island_high"])]
    if forbidden_arrays:
        issues.append("forbidden island array fields")
    return _result(CODES[6], "Named subsided compartments, spatially attached graph edges and unmodelled island deferral.", issues,
                   {"compartment_count": len(compartments), "connection_count": len(connections),
                    "connected_compartment_count": len(reached), "forbidden_island_arrays": forbidden_arrays,
                    "array_names_checked": c.arrays is not None})


def _provinces(c):
    issues = []
    provinces, blocks = c.group("geological_province"), c.group("structural_block")
    boundary_ids = set(c.group("fault_segment")) | set(c.group("non_fault_contact")) | set(c.group("massif_local_contact"))
    if set(provinces) != set(c.contract["required_province_ids"]):
        issues.append("province inventory differs")
    c.check_properties("geological_province", c.contract["required_province_properties"], issues)
    outside_areas = {}
    for pid, feature in provinces.items():
        p = feature["properties"]
        c.check_events(p, ["event_ids"], pid, issues)
        if (not _unique_strings(p["parent_block_ids"]) or not p["parent_block_ids"] or
                not set(p["parent_block_ids"]) <= set(blocks) or
                not _unique_strings(p["boundary_feature_ids"]) or not p["boundary_feature_ids"] or
                not set(p["boundary_feature_ids"]) <= boundary_ids):
            issues.append(f"{pid}: unresolved parent/boundary references")
            continue
        parent = unary_union([c.geom(blocks[bid]) for bid in p["parent_block_ids"]])
        outside = c.geom(feature).difference(parent).area
        outside_areas[pid] = outside
        if outside > AREA_EPS_KM2:
            issues.append(f"{pid}: province extends {outside} km2 outside named parent blocks")
        for bid in p["parent_block_ids"]:
            if pid not in blocks[bid]["properties"]["province_ids"]:
                issues.append(f"{pid}/{bid}: nonreciprocal province/block reference")
    for bid, feature in blocks.items():
        pids = feature["properties"]["province_ids"]
        if not _unique_strings(pids):
            issues.append(f"{bid}: invalid province list")
        for pid in pids:
            if pid not in provinces or bid not in provinces[pid]["properties"]["parent_block_ids"]:
                issues.append(f"{bid}/{pid}: nonreciprocal block/province reference")
    gate = provinces["P-GATE"]["properties"]
    if not (gate["competence"] in {"high", "very_high"} and gate["solubility"] == "negligible" and
            gate["geothermal_state"] in {"cool", "stable_cool", "inactive"} and
            "old" in gate["basement_terrane"].lower() and "E0" in gate["event_ids"]):
        issues.append("Gate is not old, cool, resistant and non-soluble")
    southern = ["P-PHOENIX", "P-EISENWEB", "P-FEUER"]
    for index, pid in enumerate(southern):
        for other in southern[index+1:]:
            if c.geom(provinces[pid]).equals(c.geom(provinces[other])):
                issues.append(f"{pid}/{other}: southern systems have identical geometry")
    if "hot" not in provinces["P-PHOENIX"]["properties"]["geothermal_state"]:
        issues.append("Phoenix lacks hot southern signature")
    if provinces["P-EISENWEB"]["properties"]["metallogenic_state"] != "high":
        issues.append("Eisenweb lacks high metallogenic signature")
    if "dormant" not in provinces["P-FEUER"]["properties"]["geothermal_state"]:
        issues.append("Feuerschuppe lacks older/dormant signature")
    return _result(CODES[7], "Province/block containment and reciprocal provenance; distinct Gate and southern attributes.", issues,
                   {"province_count": len(provinces), "outside_parent_area_km2": outside_areas})


def _sections(c):
    issues, routes, exact_matches = [], {}, {}
    display = c.documents["sections"].get("properties")
    required_display = c.contract["section_display_contract"]
    if (not isinstance(display, dict) or any(type(display.get(k)) is not type(v) or display.get(k) != v
                                             for k, v in required_display.items())):
        issues.append("section display scales differ from contract")
    traces = {}
    for feature in c.layers["section_trace"]:
        sid = feature["properties"]["section_id"]
        if sid in traces:
            issues.append(f"duplicate trace {sid}")
        traces[sid] = feature
    if set(traces) != set(c.contract["required_section_ids"]):
        issues.append("section trace inventory differs")
    by_haus = {f["properties"]["haus"]: f for f in c.layers["massif_structural_envelope"]}
    required_routes = {
        "X1": ["edelstein", "TG-W", "TG-C", "TG-E", "glanzgrund"],
        "X2": ["A-AC-W", "A-AC-CW", "A-AC-E"],
        "X3": ["eisenweb", "wiedergeborene_flamme", "feuerschuppe"],
        "X4": ["C-E", "verfuehrschlund", "laubraunen", "A-AC-E"],
    }
    faults = c.group("fault_segment")
    for sid, feature in traces.items():
        p, trace = feature["properties"], c.geom(feature)
        if p.get("source_match_mode") != "exact_plan_geometry":
            issues.append(f"{sid}: trace lacks exact-plan provenance")
        entries = c.section_entries(sid)
        present_layers = {f["properties"]["layer"] for f in entries}
        if not set(c.contract["required_section_layers"]) <= present_layers:
            issues.append(f"{sid}: missing required section content")
        routes[sid] = {}
        for name in required_routes[sid]:
            target = by_haus[name] if name in by_haus else c.by_id[name]
            hit = trace.intersects(c.geom(target))
            routes[sid][name] = hit
            if not hit:
                issues.append(f"{sid}: trace misses required {name}")
        if sid == "X3":
            stations = [trace.project(c.centroid(by_haus[name])) for name in required_routes[sid]]
            if any(b-a <= EPS_KM for a, b in zip(stations, stations[1:])):
                issues.append("X3: southern massif order differs")
        actual = {}
        trace_bounds = c.bounds(feature)
        for fid, fault in faults.items():
            if not _bounds_may_meet(trace_bounds, c.bounds(fault)):
                continue
            intersection = trace.intersection(c.geom(fault))
            if not intersection.is_empty:
                actual[fid] = sorted(_point_parts(intersection), key=trace.project)
        declared = p.get("intersected_fault_ids")
        if not _unique_strings(declared) or set(declared) != set(actual):
            issues.append(f"{sid}: declared intersected faults differ from measured map intersections")
        planes = [f for f in entries if f["properties"]["layer"] == "section_fault_plane"]
        plane_sources = Counter()
        matched = 0
        for plane in planes:
            fp, line = plane["properties"], c.geom(plane)
            ids = fp["source_feature_ids"]
            if len(ids) != 1 or ids[0] not in actual:
                issues.append(f"{sid}: section fault plane has no matching map crossing")
                continue
            fid = ids[0]
            plane_sources[fid] += 1
            point = Point(fp["map_intersection_xy_km"])
            station = fp["trace_station_km"]
            if (not _number(station) or min(point.distance(pnt) for pnt in actual[fid]) > EPS_KM or
                    abs(trace.project(point)-station) > EPS_KM or
                    abs(fp["trace_station_fraction"]-station/trace.length) > EPS_KM/trace.length or
                    Point(line.coords[0]).distance(Point(station, 0)) > EPS_KM):
                issues.append(f"{sid}/{fid}: section station/intersection geometry mismatch")
            else:
                matched += 1
            dip = faults[fid]["properties"]["dip_range_deg"]
            source_role = (faults[fid]["properties"]["downthrown_side_or_shear_sense"] or
                           faults[fid]["properties"]["structural_role"])
            end = line.coords[-1]
            actual_dip = math.degrees(math.atan2(abs(end[1]), abs(end[0]-station)))
            if (fp.get("source_match_mode") != "exact_plan_trace_intersection" or
                    fp["dip_range_deg"] != dip or not dip[0]-EPS_KM <= actual_dip <= dip[1]+EPS_KM or
                    not -required_display["depth_window_km"][1]-EPS_KM <= end[1] < -EPS_KM or
                    fp["polarity_or_role"] != source_role):
                issues.append(f"{sid}/{fid}: fault-plane dip/depth/polarity differs from mapped source")
        if plane_sources != Counter({fid: len(points) for fid, points in actual.items()}):
            issues.append(f"{sid}: exact map-crossing/section-plane multiplicity differs")
        exact_matches[sid] = {"map_crossings": sum(map(len, actual.values())), "matching_plane_stations": matched}
        for entry in entries:
            ep = entry["properties"]
            ids = ep.get("source_feature_ids")
            if not _unique_strings(ids) or not ids or not set(ids) <= set(c.by_id):
                issues.append(f"{sid}/{ep['layer']}: missing or unresolved source feature identifiers")
            if ep["layer"] != "section_trace":
                bounds = c.geom(entry).bounds
                if bounds[1] < -required_display["depth_window_km"][1]-EPS_KM or bounds[3] > EPS_KM:
                    issues.append(f"{sid}/{ep['layer']}: section depth outside display contract")
                if bounds[0] < -EPS_KM or bounds[2] > trace.length+EPS_KM:
                    issues.append(f"{sid}/{ep['layer']}: section station outside plan-trace length")
    unknown = [f["properties"].get("section_id") for f in c.sections if f["properties"].get("section_id") not in traces]
    if unknown:
        issues.append(f"unresolved section identifiers: {unknown}")
    return _result(CODES[8], "Common-scale sections recomputed against map routes, fault intersections/stations and source dips.", issues,
                   {"route_intersections": routes, "fault_station_checks": exact_matches,
                    "interpretive_subsurface_content": "Non-fault bodies/contacts/wedges are checked for source resolution and display bounds, not independently solved geological depths.",
                    "route_requirements_basis": "Reconstructed historical TRUE_MAP_MATCHED_SECTIONS gate's named targets; no PASS values reused."})


def audit_geometry(package_dir: Path, contract: dict, arrays: dict | None = None) -> list[dict]:
    """Return nine independent checks; malformed/uncertain evidence fails closed.

    The aggregator must add raster checks to the partition gate. ``arrays`` is
    optional and used only for forbidden array-name coverage; this function does
    not load the large NPZ or reuse any recorded historical audit measurements.
    """
    return _audit_geometry(package_dir, contract, arrays)


def _audit_geometry(package_dir, contract, arrays=None, *, _inputs=None):
    """Private invocation-local decoded-input route; every check recomputes."""
    if DEPENDENCY_ERROR:
        return [{**_result(code, "Geometry dependency unavailable.", [DEPENDENCY_ERROR]), "status": "BLOCKED"}
                for code in CODES]
    try:
        package_dir = Path(package_dir)
        if _inputs is None:
            documents = {name: _read(package_dir / f"{PREFIX}{name}.{extension}")
                         for name, extension in DOCUMENT_FILES}
            checkpoint = _read(package_dir / "checkpoint0-frozen-inputs.json")
        else:
            documents, checkpoint = _inputs._take(package_dir)
        c = Context(documents, checkpoint, contract, arrays)
    except Exception as exc:
        return [_result(code, "Required geometry evidence is invalid or unavailable.",
                        [f"{type(exc).__name__}: {exc}"]) for code in CODES]
    results = []
    for code, check in zip(CODES, (_inventory, _apron, _partition, _fault_graph, _blocks,
                                  _crown, _accommodation, _provinces, _sections)):
        try:
            results.append(check(c))
        except Exception as exc:
            results.append(_result(code, "Reconstructed geometry check could not establish the required condition.",
                                   [f"{type(exc).__name__}: {exc}"]))
    return results
