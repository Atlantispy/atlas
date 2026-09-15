"""NEW RECONSTRUCTED History A auditor; not the recovered historical auditor.

Read-only checks against the retained contract. Historical PASS records supply
gate identities, never fresh scientific results. Review readiness is not canon,
checkpoint acceptance, an identified-plate model, or production permission.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import zipfile

import numpy as np
from work.generator_runtime_r12 import _CapturedLoader

HERE = Path(__file__).resolve().parent
R1 = HERE.parent / "diadem_tectonics_r1"


def _load_r1(name):
    alias = f"_history_a_r3_r1_{name}"
    if alias not in sys.modules:
        source = R1 / f"{name}.py"
        spec = importlib.util.spec_from_file_location(alias, source, loader=_CapturedLoader(source))
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    return sys.modules[alias]


sources = _load_r1("sources")
array_reader = _load_r1("compare")  # Decoder only; no output-parity test is run.
PREFIX = "checkpoint1-history-a-"
CODES = tuple(sources.AUDIT_CODES)
GATE_LETTERS = dict(zip(CODES, "A A A A A A A A C B A C B C C B B C C D E F F G".split()))
GEOMETRY_CODES = (
    "VECTOR_PRIMARY_LAYER_INVENTORY", "NO_UNAPPROVED_EXTERNAL_APRON",
    "STRUCTURAL_DOMAIN_PARTITION_AND_RASTER_SCOPE", "FAULT_GRAPH_SCHEMA_AND_TOPOLOGY",
    "BLOCK_KINEMATIC_DERIVATION", "CROWN_GATE_AND_MASSIF_MODEL",
    "ACCOMMODATION_GRAPH_AND_ARTIFICIAL_ISLAND_DEFERRAL", "STRUCTURALLY_COUPLED_PROVINCES",
    "TRUE_MAP_MATCHED_SECTIONS",
)
CONTRIBUTIONS = ("block_relative_state_contribution", "fault_displacement_contribution",
                 "crown_inherited_structure_contribution", "southern_renewal_contribution")
REFERENCE_ARRAYS = {"x_km", "y_km", "approved_peak_reference_names",
                    "approved_peak_reference_xy_km", "approved_peak_reference_uncertainty_km"}
ID_LAYERS = {"fault_block_id": ("structural_block", "block_id"),
             "massif_structural_envelope_id": ("massif_structural_envelope", "massif_id"),
             "crown_system_id": ("crown_system", "crown_system_id"),
             "crown_link_id": ("crown_link", "link_id"),
             "accommodation_compartment_id": ("accommodation_compartment", "accommodation_id")}
MAX_ARRAY_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ERRORS = 50


def _check(code, status, summary, metrics=None, evidence=()):
    if status not in ("PASS", "FAIL", "BLOCKED"):
        raise ValueError("Invalid audit result status")
    return {"gate": GATE_LETTERS[code], "code": code, "status": status,
            "summary": summary, "metrics": metrics or {}, "evidence": [str(p) for p in evidence]}


def _result(code, errors, summary, metrics=None, evidence=()):
    return _check(code, "FAIL" if errors else "PASS", summary,
                  {**(metrics or {}), "error_count": len(errors), "errors": errors[:MAX_ERRORS]}, evidence)


def _identity(path):
    sources._no_links(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}


def _json(path, *, _geometry_inputs=None):
    sources._no_links(path)
    stat_size = path.stat().st_size if _geometry_inputs is not None else None
    with path.open("rb") as stream:
        raw = stream.read(sources.MAX_JSON_BYTES + 1)
    if len(raw) > sources.MAX_JSON_BYTES:
        raise ValueError(f"Oversized JSON: {path}")
    value = sources._json(raw, str(path))
    if _geometry_inputs is not None:
        _geometry_inputs._capture(path, raw, value, stat_size)
    return value


def _equal(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _features(documents):
    return [item for document in documents.values() if document.get("type") == "FeatureCollection"
            for item in document["features"]]


def _load_arrays(path):
    with zipfile.ZipFile(path) as archive:
        members = array_reader._archive_members(archive)
        if sum(item.file_size for item in members.values()) > MAX_ARRAY_TOTAL_BYTES:
            raise ValueError("Structural arrays exceed the 256 MiB decoded-input bound")
        return {name: array_reader._read_array(archive, members[name]) for name in array_reader.ARRAY_NAMES}


def _event_check(events, contract):
    errors = []
    expected = contract["required_events"]["a"]
    if events.get("schema_version") != "1.0-review" or events.get("history") != "A":
        errors.append("Wrong event schema/history")
    records = events.get("events", [])
    observed = [record.get("event_id") for record in records]
    if observed != expected or len(observed) != len(set(observed)):
        errors.append("Missing, duplicate, reordered or wrong-history event")
    for record in records:
        if any(not isinstance(record.get(key), str) or not record[key].strip()
               for key in ("event_id", "name", "structural_expression")):
            errors.append("Event lacks an explicit identity/name/structural expression")
    return _result("EVENT_CHRONOLOGY", errors, "Recomputed ordered History A event inventory.",
                   {"expected": expected, "observed": observed})


def _forbidden(value, tokens):
    lowered = str(value).lower()
    return [token for token in tokens if re.search(r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])", lowered)]


def _metadata_errors(shared, review, roles):
    errors = []
    keys = {"schema_version", "checkpoint", "status", "authority", "histories", "generator_sources",
            "production_unchanged", "master_ledger_unchanged"}
    if set(shared) != keys:
        errors.append("Shared manifest schema/control keys differ")
    for key, expected in {"schema_version": "1.0-review", "checkpoint": "checkpoint-1-structural-geology",
                          "status": "REVIEW_ONLY_NOT_ACCEPTED", "production_unchanged": True,
                          "master_ledger_unchanged": True}.items():
        if not _equal(shared.get(key), expected):
            errors.append(f"Shared metadata differs: {key}")
    histories = shared.get("histories", {})
    if (set(histories) != {"A", "B"} or not _equal(histories.get("B"),
            {"status": "not_selected_before_implementation", "artifacts": {}})):
        errors.append("History inventory or unselected History B differs")
    if (set(histories.get("A", {})) != {"status", "artifacts"} or
            histories.get("A", {}).get("status") != "selected_under_review"):
        errors.append("History A status/control keys differ")
    expected_review = {"schema_version": "1.0-review", "history": "A", "status": "PENDING",
                       "reviewer_role": "pending_independent", "items": [
                           {"role": role, "status": "PENDING",
                            "notes": "Complete evidence rendered; awaiting independent adversarial review."}
                           for role in roles]}
    if not _equal(review, expected_review):
        errors.append("Original replay pending-review identity changed or inherited historical approval")
    return errors


def _raster_checks(arrays, checkpoint, contract, features, lineage):
    schema_errors, partition_errors = [], []
    frame = checkpoint["coordinate_reference"]
    shape = (int(frame["public_frame_height"]["value"]) + 1,
             int(frame["public_frame_width"]["value"]) + 1)
    if set(arrays) != set(array_reader.ARRAY_NAMES):
        schema_errors.append("Exact retained 17-array inventory is required")
    for key in ("horizontal_unit", "x_direction", "y_direction"):
        if frame[key] != {"horizontal_unit": "km", "x_direction": "east", "y_direction": "south"}[key]:
            schema_errors.append(f"Unexpected coordinate frame {key}")
    for name, array in arrays.items():
        if name not in REFERENCE_ARRAYS and array.shape != shape:
            schema_errors.append(f"{name}: wrong full-frame shape")
        if array.dtype.kind in "fiu" and not np.isfinite(array).all():
            schema_errors.append(f"{name}: non-finite values")
        if name not in {*ID_LAYERS, "structural_model_domain_mask", "approved_peak_reference_names"} and array.dtype.kind != "f":
            schema_errors.append(f"{name}: continuous/reference coordinates require floating-point data")
        if name not in REFERENCE_ARRAYS and name != "annular_coordinate_elevation_contribution_m":
            if _forbidden(name, contract["forbidden_downstream_tokens"]):
                schema_errors.append(f"Forbidden downstream array: {name}")
    for axis, count in (("x_km", shape[1]), ("y_km", shape[0])):
        if arrays[axis].shape != (count,) or not np.array_equal(arrays[axis], np.arange(count)):
            schema_errors.append(f"{axis}: expected ordered 1 km coordinates")
    peak = checkpoint["peak_anchors"]
    order = peak["clockwise_order_from_north_west_gate_flank"]
    points = {p["haus"]: (p["x"], p["y"]) for p in peak["anchors"]}
    if arrays["approved_peak_reference_names"].dtype.kind != "U" or arrays["approved_peak_reference_names"].tolist() != order:
        schema_errors.append("Approved anchor names/order differ")
    if not np.array_equal(arrays["approved_peak_reference_xy_km"], np.asarray([points[name] for name in order])):
        schema_errors.append("Approved anchor coordinates differ")
    uncertainty = arrays["approved_peak_reference_uncertainty_km"]
    if uncertainty.shape != (len(order),) or not np.array_equal(uncertainty, np.full(len(order), 30.0)):
        schema_errors.append("Retained 30 km macro-reference uncertainty marker differs")
    if np.any(arrays["annular_coordinate_elevation_contribution_m"] != 0):
        schema_errors.append("Prohibited annular contribution is not identically zero")
    mask, block = arrays["structural_model_domain_mask"], arrays["fault_block_id"]
    if mask.dtype != np.dtype(bool) or mask.shape != shape or not mask.any() or mask.all():
        partition_errors.append("Structural domain mask must be nontrivial boolean full-frame data")
    if block.dtype.kind not in "iu" or block.shape != shape:
        partition_errors.append("Fault block raster must have full-frame integer IDs")
    elif mask.dtype == np.dtype(bool) and mask.shape == block.shape:
        sentinel = contract["fault_block_raster_contract"]["outside_sentinel"]
        if np.any(block[~mask] != sentinel) or np.any(block[mask] == sentinel):
            partition_errors.append("Fault IDs violate outside-sentinel or inside-assignment rules")
    nodes = {node["field"]: node for node in lineage["nodes"]}
    codebook_metrics = {}
    for field, (layer, id_key) in ID_LAYERS.items():
        array = arrays[field]
        book = nodes.get(field, {}).get("categorical_codebook", {})
        expected_ids = {f["properties"][id_key] for f in features if f["properties"].get("layer") == layer}
        try:
            valid_book = bool(book) and all(str(int(key)) == key and int(key) > 0 and isinstance(value, str)
                                            for key, value in book.items())
            codes = {int(key) for key in book}
        except (ValueError, TypeError):
            valid_book, codes = False, set()
        observed = set(np.unique(array).tolist()) - {0}
        if (array.dtype.kind not in "iu" or not valid_book or observed != codes or
                set(book.values()) != expected_ids or len(set(book.values())) != len(book)):
            partition_errors.append(f"{field}: observed IDs/vector IDs/codebook disagree")
        codebook_metrics[field] = {"observed_codes": sorted(observed), "codebook_count": len(book),
                                   "vector_id_count": len(expected_ids)}
    raster = _result("RASTER_SCHEMA_ZERO_SENTINEL_AND_SCOPE", schema_errors,
                     "Recomputed raster schema, macro references, zero sentinel and prohibited scope.",
                     {"grid_shape": list(shape), "array_count": len(arrays),
                      "uncertainty_rule": "30 km is the retained implementation marker, not a newly estimated scientific uncertainty."})
    partition = _result("STRUCTURAL_DOMAIN_PARTITION_AND_RASTER_SCOPE", partition_errors,
                        "Independent raster portion; vector partition must also pass.",
                        {"raster_checks": codebook_metrics, "portion": "raster_only"})
    return raster, partition


def _lineage_check(arrays, lineage, features, contract):
    errors = []
    if lineage.get("schema_version") != "1.0-review" or lineage.get("history") != "A":
        errors.append("Wrong lineage schema/history")
    nodes = lineage.get("nodes", [])
    fields = [n.get("field") for n in nodes]
    required = set(arrays) - REFERENCE_ARRAYS
    if len(fields) != len(set(fields)) or set(fields) != required:
        errors.append("Missing, extra or duplicate physical lineage node")
    by_name = {n["field"]: n for n in nodes}
    known_ids = {value for f in features for key, value in f["properties"].items()
                 if key.endswith("_id") and isinstance(value, str)}
    actual_hashes = {name: hashlib.sha256(array_reader._array_bytes(array)).hexdigest() for name, array in arrays.items()}
    if not _equal(lineage.get("array_hashes"), actual_hashes):
        errors.append("Lineage array hashes do not exactly bind all decoded fields")
    for node in nodes:
        name, parents, ids = node["field"], node.get("parents"), node.get("feature_ids")
        if (not isinstance(parents, list) or len(parents) != len(set(parents)) or
                any(parent not in set(arrays) | {"vector_features"} for parent in parents)):
            errors.append(f"{name}: invalid/unresolved parent")
        if not isinstance(ids, list) or len(ids) != len(set(ids)) or any(i not in known_ids for i in ids):
            errors.append(f"{name}: unresolved/nonunique finite-feature provenance")
        if not isinstance(node.get("operation"), str) or not node["operation"].strip():
            errors.append(f"{name}: missing operation")
        text = json.dumps({k: v for k, v in node.items() if k != "categorical_codebook"})
        if _forbidden(text, contract["forbidden_lineage_tokens"]):
            errors.append(f"{name}: prohibited radial/analytic lineage token")
        if name in CONTRIBUTIONS and np.any(arrays[name] != 0) and not ids:
            errors.append(f"{name}: nonzero contribution lacks finite feature IDs")
    visiting, visited = set(), set()
    def visit(name):
        if name in visiting:
            return True
        if name in visited or name not in by_name:
            return False
        visiting.add(name)
        cycle = any(visit(parent) for parent in by_name[name].get("parents", []) if isinstance(parent, str))
        visiting.remove(name)
        visited.add(name)
        return cycle
    if any(visit(name) for name in by_name):
        errors.append("Lineage contains a directed cycle")
    reconstruction = lineage.get("reconstruction", {})
    tolerance = reconstruction.get("tolerance")
    if (reconstruction.get("total_array") != "relative_structural_potential" or
            reconstruction.get("contribution_arrays") != list(CONTRIBUTIONS) or
            type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0 or
            tolerance > contract["hard_thresholds"]["reconstruction_tolerance"]):
        errors.append("Reconstruction declaration differs or relaxes the contract tolerance")
        tolerance = 0.0
    if by_name.get("relative_structural_potential", {}).get("parents") != list(CONTRIBUTIONS):
        errors.append("Total lineage parents differ from its contribution declaration")
    total = arrays["relative_structural_potential"]
    maximum = 0.0
    if any(arrays[name].shape != total.shape for name in CONTRIBUTIONS):
        errors.append("Contribution/total shapes differ")
    else:
        # Bound additional arithmetic memory: retained producer's summation order,
        # only 32 rows at a time. No tolerance is silently raised.
        for start in range(0, total.shape[0], 32):
            selection = slice(start, start + 32)
            reconstructed = arrays[CONTRIBUTIONS[0]][selection] + arrays[CONTRIBUTIONS[1]][selection]
            reconstructed = reconstructed + arrays[CONTRIBUTIONS[2]][selection]
            reconstructed = reconstructed + arrays[CONTRIBUTIONS[3]][selection]
            residual = np.abs(reconstructed - total[selection])
            if not np.isfinite(residual).all():
                errors.append("Non-finite reconstruction residual")
                break
            maximum = max(maximum, float(residual.max(initial=0)))
        if maximum > tolerance:
            errors.append("Stored contributions do not reconstruct within the declared tolerance")
    return _result("COMPLETE_NONRADIAL_LINEAGE_AND_RECONSTRUCTION", errors,
                   "Fresh DAG, finite-feature lineage, decoded-array hashes and arithmetic reconstruction checks.",
                   {"node_count": len(nodes), "array_hash_count": len(actual_hashes),
                    "maximum_reconstruction_residual": maximum, "declared_tolerance": tolerance})


def _visual_check(path, package, contract, manifest):
    code = "COMPLETE_VISUAL_EVIDENCE"
    if path is None:
        return _check(code, "BLOCKED", "A NEW hash-bound independent visual review is required; historical PASS is not reused.")
    try:
        document = _json(Path(path))
        expected_keys = {"schema", "history", "status", "reviewer_role", "review_kind", "contract_sha256",
                         "package_manifest_sha256", "items", "production_authorized"}
        errors = []
        if set(document) != expected_keys:
            errors.append("New visual companion schema/key inventory differs")
        for key, value in {"schema": "diadem.tectonics.independent-visual-review.v1", "history": "A",
                           "reviewer_role": "independent", "review_kind": "NEW_INDEPENDENT_ENGINEERING_VISUAL_REVIEW",
                           "production_authorized": False}.items():
            if not _equal(document.get(key), value):
                errors.append(f"Invalid fresh visual-review identity: {key}")
        if document.get("status") not in ("PASS", "FAIL"):
            errors.append("New visual review status must be PASS or FAIL")
        if document.get("contract_sha256") != _identity(package / Path(sources.CONTRACT).name)["sha256"]:
            errors.append("Visual review binds a different contract")
        if document.get("package_manifest_sha256") != _identity(package / Path(sources.SHARED).name)["sha256"]:
            errors.append("Visual review binds a different package manifest")
        items = document.get("items", [])
        if not isinstance(items, list) or [item.get("role") for item in items] != contract["required_visual_roles"]:
            errors.append("New visual review must cover all eleven ordered roles")
        else:
            for item, original in zip(items, manifest["artifacts"]):
                if set(item) != {"role", "path", "sha256", "status", "notes"}:
                    errors.append(f"Invalid visual item keys: {item.get('role')}")
                filename = f"{PREFIX}{item['role'].replace('_', '-')}-review-only.png"
                if (item.get("path") != filename or not _sha(item.get("sha256")) or
                        item.get("sha256") != original["sha256"] or
                        item.get("sha256") != _identity(package / filename)["sha256"]):
                    errors.append(f"Wrong role/path/image hash: {item.get('role')}")
                if item.get("status") != "PASS":
                    errors.append(f"Visual role did not pass: {item.get('role')}")
                if not isinstance(item.get("notes"), str) or not item["notes"].strip():
                    errors.append(f"Missing actual review notes: {item.get('role')}")
        if document.get("status") != "PASS":
            errors.append("New independent visual review did not pass")
        return _result(code, errors, "New independent visual evidence, exact role/image/package/contract bindings.",
                       {"historical_review_used_as_fresh_evidence": False}, (path,))
    except (OSError, ValueError, TypeError, KeyError, sources.SourceGateError) as exc:
        return _check(code, "FAIL", "Invalid fresh visual-review companion.", {"error": str(exc)}, (path,))


def _aggregate(checks):
    if (set(checks) != set(CODES) or any(row.get("code") != code or
            row.get("status") not in ("PASS", "FAIL", "BLOCKED") for code, row in checks.items())):
        raise ValueError("Exactly the 24 original gate identities are required")
    for code, dependencies in (
        ("EVERY_RETAINED_HISTORY_PASSES_A_TO_E", CODES[:21]),
        ("READY_FOR_MICHAEL_CHECKPOINT_REVIEW", CODES[:-1]),
    ):
        upstream = [checks[name] for name in dependencies]
        failed = [row["code"] for row in upstream if row["status"] == "FAIL"]
        blocked = [row["code"] for row in upstream if row["status"] == "BLOCKED"]
        status = "FAIL" if failed else "BLOCKED" if blocked else "PASS"
        checks[code] = _check(code, status, "Recomputed prerequisite aggregation; this is review readiness only.",
                              {"failed_prerequisites": failed, "blocked_prerequisites": blocked})
    ordered = [checks[code] for code in CODES]
    counts = {status.lower() + "_count": sum(row["status"] == status for row in ordered)
              for status in ("PASS", "FAIL", "BLOCKED")}
    overall = "FAIL" if counts["fail_count"] else "BLOCKED" if counts["blocked_count"] else "PASS"
    return ordered, {**counts, "overall_status": overall,
                     "review_readiness": checks[CODES[-1]]["status"],
                     "checkpoint_acceptance": "NOT_ESTABLISHED_BY_THIS_AUDIT",
                     "plate_domain_snapshot_authority": "NOT_ESTABLISHED_BY_THIS_AUDIT",
                     "production_authorized": False, "category_complete": False}


def audit_package(package_dir: Path, replay_root: Path, visual_review_path: Path | None = None) -> dict:
    package, root = Path(package_dir), Path(replay_root)
    checks = {code: _check(code, "BLOCKED", "Required evidence has not been checked.") for code in CODES}
    report = {"schema": "diadem.tectonics.reconstructed-audit.v1", "implementation_kind": "NEW_RECONSTRUCTED_AUDITOR",
              "created_utc": datetime.now(timezone.utc).isoformat(), "history": "A",
              "package_dir": str(package), "replay_root": str(root), "production_authorized": False,
              "recovered_original_auditor": False, "output_parity_used_as_scientific_validation": False,
              "evidence": {}, "limits": [
                  "Checks reconstruct the retained review contract; they do not recover the original auditor implementation.",
                  "The 30 km macro-reference uncertainty value is a retained implementation marker, not a new scientific estimate.",
                  "A full PASS establishes readiness for Michael's checkpoint review, not checkpoint acceptance or production authority.",
                  "Identified tectonic plates, motion vectors and current domain snapshot authority are outside this structural-history audit.",
              ]}
    before_sources = None
    tracked = {}
    arrays = {}
    geometry_module = None
    try:
        if not package.is_absolute() or not root.is_absolute() or package != root / "sandbox" / sources.REBUILD:
            raise ValueError("Package must be the exact sandbox/work/stage4-rebuild child of the supplied replay root")
        sources._no_links(package)
        sources._no_links(root)
        before_sources = sources.inspect_sources()
        if not before_sources["review_replay_source_gate_passed"]:
            failed = any(row["status"] == "HASH_MISMATCH" for row in before_sources["files"])
            checks["AUDIT_CONTRACT"] = _check("AUDIT_CONTRACT", "FAIL" if failed else "BLOCKED",
                                              "Historical source authority is unavailable or changed.",
                                              {"issues": before_sources["issues"]})
            raise RuntimeError("source prerequisites unavailable")
        source_pins = {row["relative_path"]: row for row in before_sources["files"]}
        geometry_path = HERE / "geometry_audit.py"
        sources._no_links(geometry_path)
        from work.diadem_tectonics_r3 import geometry_audit as geometry_module
        if Path(geometry_module.__file__).resolve() != geometry_path.resolve():
            raise ValueError("Geometry companion module path differs")
        decoded_geometry = geometry_module._DecodedInputs(package)
        contract_path = package / Path(sources.CONTRACT).name
        checkpoint_path = package / Path(sources.CHECKPOINT0).name
        contract = _json(contract_path)
        checkpoint = _json(checkpoint_path, _geometry_inputs=decoded_geometry)
        audit_identity = _identity(Path(source_pins[sources.AUDIT]["resolved_path"]))
        historical = _json(Path(source_pins[sources.AUDIT]["resolved_path"]))
        if [row["code"] for row in historical["checks"]] != list(CODES):
            raise ValueError("Historical gate identity inventory differs")
        report["historical_audit_evidence"] = {**audit_identity, "used_for": "contract/gate reconstruction only; historical statuses are not copied"}
        for relative in (sources.CHECKPOINT0, *sources.SOURCE_PATHS):
            path = package / Path(relative).name
            tracked[path] = _identity(path)
            if tracked[path]["sha256"] != source_pins[relative]["expected_sha256"]:
                raise ValueError(f"Staged source/control differs from the hash-bound review recipe: {relative}")
        checks["AUDIT_CONTRACT"] = _check("AUDIT_CONTRACT", "PASS", "Exact retained audit contract and historical gate identities authenticated; auditor is newly reconstructed.",
                                          {"contract_sha256": tracked[contract_path]["sha256"]}, (contract_path,))
        checks["CHECKPOINT0_AUTHORITY"] = _check("CHECKPOINT0_AUTHORITY", "PASS", "Frozen Checkpoint 0 and all authority/freeze pins freshly verified by the read-only source gate.",
                                                {"sha256": tracked[checkpoint_path]["sha256"]}, (checkpoint_path,))
        peak = checkpoint["peak_anchors"]
        points = {p["haus"]: (p["x"], p["y"]) for p in peak["anchors"]}
        ordered = np.asarray([points[name] for name in peak["clockwise_order_from_north_west_gate_flank"]], dtype="<f8")
        digest = hashlib.sha256(ordered.tobytes()).hexdigest()
        checks["APPROVED_TRANSFER_REFERENCE_AUTHORITY"] = _result(
            "APPROVED_TRANSFER_REFERENCE_AUTHORITY", [] if digest == contract["authority"]["approved_coordinate_sha256"] else ["Approved coordinate hash differs"],
            "Fresh ordered-coordinate reconstruction bound to accepted macro references, not summit heights.",
            {"anchor_count": len(points), "computed_coordinate_sha256": digest}, (checkpoint_path, contract_path))
        shared_path = package / Path(sources.SHARED).name
        shared = _json(shared_path)
        pending_review = _json(package / (PREFIX + "visual-review.json"))
        meta_errors = _metadata_errors(shared, pending_review, contract["required_visual_roles"])
        checks["SHARED_PACKAGE_MANIFEST"] = _result("SHARED_PACKAGE_MANIFEST", meta_errors, "Independently checked shared-manifest identity, scope and status.", evidence=(shared_path,))
        expected_authority = {"checkpoint0_manifest_sha256": sources.BOOTSTRAP_PINS[sources.CHECKPOINT0],
                              "approved_coordinate_sha256": sources.COORDINATE_SHA256,
                              "anchor_source_review_sha256": sources.ANCHOR_SHA256,
                              "selected_history": "A", "selection_verbatim": "I choose A"}
        checks["SHARED_AUTHORITY_HASHES"] = _result("SHARED_AUTHORITY_HASHES", [] if _equal(shared.get("authority"), expected_authority) else ["Shared authority identity or hashes differ"],
                                                   "Shared authority fields independently rebound to authenticated controls.", evidence=(shared_path, contract_path))
        artifacts = shared["histories"]["A"]["artifacts"]
        pin_errors = []
        if set(artifacts) != set(sources.ARTIFACT_PATHS):
            pin_errors.append("Nine artifact identities required")
        pins = list(artifacts.values()) + shared["generator_sources"]
        if [pin["path"] for pin in shared["generator_sources"]] != sources.SOURCE_PATHS:
            pin_errors.append("Four ordered producer/control identities differ")
        for role, relative in sources.ARTIFACT_PATHS.items():
            if artifacts.get(role, {}).get("path") != relative:
                pin_errors.append(f"Artifact role/path mismatch: {role}")
        for pin in pins:
            if set(pin) != {"path", "sha256"} or not _sha(pin["sha256"]):
                raise ValueError("Malformed artifact/source pin")
            relative = sources._relative(pin["path"])
            if relative not in {*sources.ARTIFACT_PATHS.values(), *sources.SOURCE_PATHS}:
                raise ValueError("Unexpected artifact path")
            path = root / "sandbox" / relative
            tracked[path] = _identity(path)
            if tracked[path]["sha256"] != pin["sha256"]:
                pin_errors.append(f"Artifact SHA256 mismatch: {relative}")
        checks["HASH_BOUND_HISTORY_ARTIFACTS"] = _result("HASH_BOUND_HISTORY_ARTIFACTS", pin_errors,
                                                        "Fresh artifact/source identity and SHA256 checks; no historical output equality is assumed.", evidence=(shared_path,))
        geometry_suffixes = {f"{name}.{extension}" for name, extension in geometry_module.DOCUMENT_FILES}
        documents = {suffix: _json(package / (PREFIX + suffix),
                                  _geometry_inputs=decoded_geometry if suffix in geometry_suffixes else None)
                     for suffix in array_reader.JSON_PRODUCTS}
        arrays = _load_arrays(package / (PREFIX + "structural-fields.npz"))
        for suffix, document in documents.items():
            if suffix.endswith(".geojson") and (document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list)):
                raise ValueError(f"Invalid FeatureCollection: {suffix}")
        features = _features(documents)
        checks["READABLE_HISTORY_PACKAGE"] = _check("READABLE_HISTORY_PACKAGE", "PASS",
                                                     "Fresh strict JSON plus bounded 17-member NPZ header/payload/CRC decoding without pickle.",
                                                     {"decoded_bytes": sum(a.nbytes for a in arrays.values()), "array_count": len(arrays), "json_product_count": len(documents)})
        checks["EVENT_CHRONOLOGY"] = _event_check(documents["events.json"], contract)
        raster, partition = _raster_checks(arrays, checkpoint, contract, features, documents["lineage.json"])
        checks[raster["code"]] = raster
        checks["COMPLETE_NONRADIAL_LINEAGE_AND_RECONSTRUCTION"] = _lineage_check(arrays, documents["lineage.json"], features, contract)
        try:
            # Fresh strictly decoded inputs belong only to this invocation.
            # All geometric calculations remain independent recomputations.
            geometry_results = geometry_module._audit_geometry(package, contract, arrays,
                                                                 _inputs=decoded_geometry)
            if len(geometry_results) != len(GEOMETRY_CODES) or {row["code"] for row in geometry_results} != set(GEOMETRY_CODES):
                raise ValueError("Geometric result identity inventory differs")
            for row in geometry_results:
                checked = _check(row["code"], row["status"], row["summary"], row.get("metrics"), row.get("evidence", []))
                if row["code"] == partition["code"]:
                    statuses = (row["status"], partition["status"])
                    checked["status"] = "FAIL" if "FAIL" in statuses else "BLOCKED" if "BLOCKED" in statuses else "PASS"
                    checked["metrics"] = {"geometry": row.get("metrics", {}), "raster": partition["metrics"]}
                    checked["summary"] = "Combined independently recomputed vector partition and raster mask/ID contract."
                checks[row["code"]] = checked
        except (ImportError, OSError, ValueError, TypeError, KeyError) as exc:
            for code in GEOMETRY_CODES:
                checks[code] = _check(code, "BLOCKED", "Geometric auditor unavailable or returned invalid evidence.", {"error": str(exc)})
        visual_path = package / (PREFIX + "visual-manifest.json")
        visual = _json(visual_path)
        visual_errors = []
        if (set(visual) != {"schema_version", "history", "status", "artifacts"} or visual.get("schema_version") != "1.0-review" or visual.get("history") != "A" or
                visual.get("status") != "COMPLETE_AWAITING_INDEPENDENT_REVIEW" or [p.get("role") for p in visual.get("artifacts", [])] != contract["required_visual_roles"]):
            visual_errors.append("Candidate visual manifest identity/status/role inventory differs")
        for pin in visual["artifacts"]:
            filename = f"{PREFIX}{pin['role'].replace('_', '-')}-review-only.png"
            if set(pin) != {"role", "path", "sha256"} or pin["path"] != f"{sources.REBUILD}/{filename}" or not _sha(pin["sha256"]):
                raise ValueError("Visual manifest role/path/pin differs")
            tracked[package / filename] = _identity(package / filename)
            if tracked[package / filename]["sha256"] != pin["sha256"]:
                visual_errors.append(f"Image hash mismatch: {filename}")
        checks["COMPLETE_VISUAL_EVIDENCE"] = (_result("COMPLETE_VISUAL_EVIDENCE", visual_errors, "Candidate visual artifact binding failed.")
                                              if visual_errors else _visual_check(visual_review_path, package, contract, visual))
        if visual_review_path is not None:
            tracked[Path(visual_review_path)] = _identity(Path(visual_review_path))
        scope_errors = []
        if contract.get("selected_history") != "a" or contract["history_selection"]["history_b_status"] != "not_selected_before_implementation":
            scope_errors.append("Selected-history contract differs")
        for item in features:
            props = item["properties"]
            if props.get("alternative", "A") != "A":
                scope_errors.append("Nonselected history geometry")
            if _forbidden(props.get("layer", ""), contract["forbidden_downstream_tokens"]):
                scope_errors.append(f"Downstream physical layer: {props.get('layer')}")
        checks["SELECTED_HISTORY_SCOPE"] = _result("SELECTED_HISTORY_SCOPE", scope_errors,
                                                   "Selected History A and structural-only feature scope checked; no B generation or modern terrain claim.")
        # Bind replay preservation to checked receipts and bytes, not the old
        # producer's hard-coded 'production_unchanged' booleans.
        receipt_paths = [root / name for name in ("REPLAY_REPORT.json", "sources-before.json", "sources-after.json")]
        receipts = [_json(path) for path in receipt_paths]
        for path in (*receipt_paths, shared_path, package / (PREFIX + "vector-skeleton-preview.png"), package / (PREFIX + "evidence-contact-sheet-review-only.jpg")):
            tracked[path] = _identity(path)
        replay, old_before, old_after = receipts
        fingerprint = lambda r: {row["resolved_path"]: row["actual_sha256"] for row in r["files"]}
        preservation_errors = []
        if (replay.get("status") != "PASS_REVIEW_REPLAY_ONLY" or replay.get("production_authority_established") is not False or
                replay.get("legacy_nonmutation_flags_used_as_evidence") is not False or replay.get("source_fingerprint") != fingerprint(before_sources) or
                fingerprint(old_before) != fingerprint(before_sources) or fingerprint(old_after) != fingerprint(before_sources)):
            preservation_errors.append("Replay source-preservation receipts do not match freshly verified protected sources")
        for row in replay["files"]:
            relative = sources._relative(row["path"])
            path = root / "sandbox" / relative
            if path not in tracked or row["sha256"] != tracked[path]["sha256"] or row["bytes"] != tracked[path]["bytes"]:
                preservation_errors.append(f"Replay receipt product identity differs: {relative}")
        expected_files = {*[str(Path(sources.REBUILD) / Path(p).name).replace('\\', '/') for p in (sources.CHECKPOINT0, *sources.SOURCE_PATHS)],
                          *sources.ARTIFACT_PATHS.values(), sources.SHARED,
                          *[f"{sources.REBUILD}/{PREFIX}{role.replace('_', '-')}-review-only.png" for role in contract["required_visual_roles"]],
                          f"{sources.REBUILD}/{PREFIX}vector-skeleton-preview.png", f"{sources.REBUILD}/{PREFIX}evidence-contact-sheet-review-only.jpg"}
        actual_files = set()
        for path in (root / "sandbox").rglob("*"):
            sources._no_links(path)
            if path.is_file():
                actual_files.add(path.relative_to(root / "sandbox").as_posix())
        receipt_files = [row["path"] for row in replay["files"]]
        if (actual_files != expected_files or len(receipt_files) != len(expected_files) or
                set(receipt_files) != expected_files):
            preservation_errors.append("Sandbox/receipt exact file inventory differs")
        checks["PRODUCTION_AND_MASTER_UNCHANGED"] = _result("PRODUCTION_AND_MASTER_UNCHANGED", preservation_errors,
                                                           "Replay receipt identities plus fresh protected-source checks; legacy booleans are not evidence.", evidence=receipt_paths)
    except Exception as exc:
        report["inspection_error"] = f"{type(exc).__name__}: {exc}"
        if checks["AUDIT_CONTRACT"]["status"] == "PASS":
            checks["READABLE_HISTORY_PACKAGE"] = _check("READABLE_HISTORY_PACKAGE", "FAIL", "Required package data or audit prerequisites could not be checked.", {"error": report["inspection_error"]})
        elif "source prerequisites unavailable" not in str(exc):
            checks["AUDIT_CONTRACT"] = _check("AUDIT_CONTRACT", "FAIL", "Authority/recipe or package identity could not be established.", {"error": report["inspection_error"]})
    finally:
        drift = []
        for path, identity in tracked.items():
            try:
                if _identity(path) != identity:
                    drift.append(str(path))
            except (OSError, sources.SourceGateError) as exc:
                drift.append(f"{path}: {exc}")
        if before_sources is not None and before_sources.get("review_replay_source_gate_passed"):
            try:
                after_sources = sources.inspect_sources()
                before_hashes = {r["resolved_path"]: r["actual_sha256"] for r in before_sources["files"]}
                after_hashes = {r["resolved_path"]: r["actual_sha256"] for r in after_sources["files"]}
                if not after_sources["review_replay_source_gate_passed"] or before_hashes != after_hashes:
                    drift.append("Protected historical source closure changed during the audit")
            except Exception as exc:
                drift.append(f"Final source check failed: {exc}")
        if drift:
            checks["PRODUCTION_AND_MASTER_UNCHANGED"] = _result("PRODUCTION_AND_MASTER_UNCHANGED", drift,
                                                                "Source/evidence drift blocks review readiness.")
        report["evidence"] = {str(path): identity for path, identity in tracked.items()}
        report["checks"], report["summary"] = _aggregate(checks)
        report["overall_status"] = report["summary"]["overall_status"]
        implementation_paths = [Path(__file__), R1 / "sources.py", R1 / "compare.py"]
        if geometry_module is not None:
            implementation_paths.append(Path(geometry_module.__file__))
        report["implementation"] = {str(path): _identity(path) for path in implementation_paths}
        shapely_module = sys.modules.get("shapely")
        report["runtime"] = {"python": sys.version, "numpy": np.__version__,
                             "shapely": getattr(shapely_module, "__version__", None),
                             "maximum_decoded_array_bytes": MAX_ARRAY_TOTAL_BYTES}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--visual-review", type=Path)
    arguments = parser.parse_args()
    result = audit_package(arguments.package, arguments.replay_root, arguments.visual_review)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if result["overall_status"] == "PASS" else 2)
