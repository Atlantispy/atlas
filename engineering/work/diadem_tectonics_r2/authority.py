"""Read-only identity closure for the retained, narrowly accepted C1C package.

Public entry point uses fixed historical pins, never caller-supplied approval.
This authenticates the preserved acceptance, not a fresh scientific/visual audit.
It neither promotes all History A nor authorises this run to make downstream data.
No historical Python is imported/executed and no NPZ is decompressed/resampled.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType


LEGACY = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted/work/stage4-rebuild")
C1C_ROOT = LEGACY / "checkpoint1c-open-scientific-package"
MANIFEST = "checkpoint1c-open-package-manifest.json"
ACCEPTANCE = "acceptance/checkpoint1c-user-acceptance.json"
PROVENANCE = "provenance/checkpoint1c-constraint-atlas-provenance.json"
AUDIT = "audits/checkpoint1c-independent-adversarial-audit.json"
STATUS = "checkpoint1c-status.json"
CONTROL_PINS = MappingProxyType({
    MANIFEST: "83a92ed4d8f7a5c5292d0af8c7adb3c8d9aadbc3cd32be0d95ac1e61049d22f9",
    ACCEPTANCE: "49940fa9bad7396572f9665156747dd4eb068b4a723b10f2f1f5f81347c8af9e",
    PROVENANCE: "df46e24da8c7529c6547b50ca0a40c34fa79a3b35b38c67222a12300b74fbd48",
    AUDIT: "a759c5c7cb3d050000271b7d444dc6d19eb30dad80dd3dd070db5126037dcf79",
})
OLD_MANIFEST_SHA = "b74ffc6ca20ca77dd5362df802cd1aa86b1cf2fa2a05ba0a7a28b53695ee9b69"
HISTORY_INPUTS = (
    "checkpoint1-history-a-faults-blocks.geojson", "checkpoint1-history-a-accommodation.geojson",
    "checkpoint1-history-a-provinces.geojson", "checkpoint1-history-a-audit.json",
    "checkpoint1-history-a-events.json",
)
HISTORY_AUDIT_SHA = "6900fe302774b8c7e4d754a15c0596857f9270e6cd1b2bf2186339388d3fbe9e"
PRODUCT_CLASS = "pre-topography 2-D/2.5-D lithotectonic constraint atlas"
SCOPE = "continuous geological constraints and uncertainty only"
COORDINATES = {
    "public": "local Cartesian; x east km; y north km",
    "raster": "row 0 northmost; cell centres x=0.5..1949.5, y=1649.5..0.5",
    "source": "History-A x east, y south/down-page", "transform": "y_north = 1650 - y_source",
    "cell_size_km": 1.0, "shape_rows_columns": [1650, 1950],
}
SCOPE_STATUSES = {
    "build_integrity_status": "PASS", "internal_consistency_status": "PASS",
    "scientific_validation_status": "PASS", "three_dimensional_framework_status": "DEFERRED",
    "categorical_reference_realization_status": "REVIEW_ONLY", "detailed_topography_stage_status": "BLOCKED",
    "hydrology_stage_status": "BLOCKED", "user_acceptance_status": "ACCEPTED",
    "macro_topography_stage_status": "ELIGIBLE", "final_outcrop_status": "DEFERRED_UNTIL_TOPOGRAPHY_AND_EROSION",
}
SOURCE_ROLES = {
    "checkpoint1c-constraint-atlas-fields.npz": ("analytical", "authoritative_pre_topography_constraint_fields"),
    "checkpoint1c-constraint-atlas-metadata.json": ("analytical", "field_registry_and_scope_metadata"),
    "checkpoint1c-constraint-atlas-structures.geojson": ("analytical", "accepted_structural_context_in_public_frame"),
    "checkpoint1c-primary-haus-constraint-traceability.json": ("traceability", "post_generation_primary_haus_requirement_traceability"),
    "checkpoint1c-primary-haus-constraint-traceability.csv": ("traceability", "open_tabular_primary_haus_requirement_traceability"),
    "checkpoint1c-hydrofacies-constraints.json": ("hydrogeology", "conceptual_hydrofacies_and_gate_constraints_not_flow_model"),
    "checkpoint1c-hydrofacies-units.csv": ("hydrogeology", "open_tabular_hydrofacies_priors"),
    "checkpoint1c-constraint-atlas-audit.json": ("audits", "builder_integrity_and_internal_consistency_audit"),
    "checkpoint1c-constraint-atlas-provenance.json": ("provenance", "atlas_input_output_hashes_and_scientific_sources"),
    "CHECKPOINT1C_CONSTRAINT_ATLAS_REVIEW.md": ("review", "human_readable_checkpoint_review"),
    "checkpoint1c-constraint-atlas-full-review-only.png": ("review", "full_frame_scientific_review_plate"),
    "checkpoint1c-constraint-atlas-gate-review-only.png": ("review", "gate_scientific_review_plate"),
    "checkpoint1c-constraint-atlas-great-forest-review-only.png": ("review", "great_forest_scientific_review_plate"),
    "checkpoint1c-constraint-atlas-southern-arc-review-only.png": ("review", "southern_arc_scientific_review_plate"),
    "checkpoint1c-constraint-atlas-west-north-review-only.png": ("review", "west_north_scientific_review_plate"),
    "CHECKPOINT1C_SCIENTIFIC_METHOD.md": ("methods", "reduced_scope_scientific_method"),
    "CHECKPOINT1C_PACKAGE_CONTRACT.md": ("methods", "fail_closed_package_contract"),
    "build_checkpoint1c_constraint_atlas.py": ("methods", "constraint_atlas_builder_source"),
    "build_checkpoint1c_open_scientific_package.py": ("methods", "open_package_builder_source"),
    "verify_checkpoint1c_open_scientific_package.py": ("methods", "external_package_verifier_source"),
    "checkpoint1c-user-acceptance.json": ("acceptance", "explicit_user_checkpoint_decision"),
    "CHECKPOINT1C_USER_ACCEPTANCE.md": ("acceptance", "human_readable_user_checkpoint_decision"),
    "checkpoint1c-independent-adversarial-audit.json": ("audits", "independent_reduced_scope_scientific_audit"),
    "CHECKPOINT1C_INDEPENDENT_ADVERSARIAL_AUDIT.md": ("audits", "independent_audit_human_readable_report"),
}
EXTRA_OUTPUTS = {STATUS, "README.md", "tables/field-catalog.csv", "tables/package-source-index.csv"}
AUDITED_NAMES = tuple(SOURCE_ROLES)[:15]
PROVENANCE_OUTPUTS = tuple(name for name in AUDITED_NAMES if name != Path(PROVENANCE).name)
OTHER_INPUTS = ("checkpoint1b-unit-catalog.json", "PRIMARY_HAUS_GEOLOGICAL_REQUIREMENTS_REVIEW.md", "checkpoint0-frozen-inputs.json")
MAX_JSON = 4 * 1024 * 1024
MAX_FILE = 128 * 1024 * 1024


class AuthorityError(ValueError):
    pass


def _same(actual, expected, label):
    if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
        raise AuthorityError(f"{label} differs")


def _text(value):
    if type(value) is not str or not value.strip():
        raise AuthorityError("nonblank text required")
    return value


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AuthorityError("invalid SHA-256")
    return value


def _relative(value):
    _text(value)
    parts = value.split("/")
    devices = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    devices.update(f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³")
    if ("\\" in value or ":" in value or "\x00" in value or
            any(not p or p in {".", ".."} or p.endswith((".", " ")) or
                p.split(".", 1)[0].upper() in devices for p in parts)):
        raise AuthorityError(f"unsafe package-relative path: {value!r}")
    return value


def _plain(path):
    raw = os.fspath(path)
    if "\x00" in raw or raw.replace("\\", "/").startswith(("//", "/??/")) or ".." in raw.replace("\\", "/").split("/"):
        raise AuthorityError("plain local non-traversing input required")
    path = Path(path).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise AuthorityError(f"linked/reparse input: {part}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise AuthorityError(f"hard-linked input: {part}")
    return path


def _identity(path):
    path = _plain(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
        raise AuthorityError(f"not a bounded regular input: {path}")
    size = 0
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            if size > MAX_FILE:
                raise AuthorityError("input grew beyond bounded scope")
            digest.update(chunk)
    if size != info.st_size:
        raise AuthorityError(f"input size changed while hashing: {path}")
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": size}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise AuthorityError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite(value):
    if type(value) is float and not math.isfinite(value):
        raise AuthorityError("nonfinite JSON value")
    if type(value) is list:
        for item in value:
            _finite(item)
    elif type(value) is dict:
        for item in value.values():
            _finite(item)


def _json(path, expected):
    path = _plain(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON or hashlib.sha256(raw).hexdigest() != _sha(expected):
        raise AuthorityError(f"bounded JSON identity mismatch: {path}")
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityError(f"invalid JSON: {path}") from exc
    _finite(value)
    if type(value) is not dict:
        raise AuthorityError("JSON control must be an object")
    return value


def _pin_list(items, *, source=False):
    if type(items) is not list:
        raise AuthorityError("manifest inventory must be a list")
    result = {}
    names = set()
    for row in items:
        keys = {"source_path", "package_path", "role", "authority_status", "sha256", "bytes"} if source else {"path", "sha256", "bytes"}
        if type(row) is not dict or set(row) != keys:
            raise AuthorityError("manifest file row schema differs")
        path = _relative(row["package_path" if source else "path"])
        _sha(row["sha256"])
        if type(row["bytes"]) is not int or not 0 <= row["bytes"] <= MAX_FILE:
            raise AuthorityError("invalid declared byte count")
        if path.casefold() in names:
            raise AuthorityError("duplicate/aliased package path")
        names.add(path.casefold())
        if source:
            original = _relative(row["source_path"])
            if "/" in original or original not in SOURCE_ROLES:
                raise AuthorityError("unrecognised logical source name")
            folder, role = SOURCE_ROLES[original]
            _same((path, row["role"]), (f"{folder}/{original}", role), "source role/path")
            _text(row["authority_status"])
        result[path] = row
    return result


def _named_pins(rows):
    if type(rows) is not list:
        raise AuthorityError("provenance pins must be a list")
    result = {}
    for row in rows:
        if type(row) is not dict or set(row) != {"path", "sha256"}:
            raise AuthorityError("provenance pin schema differs")
        name = _relative(row["path"])
        if "/" in name or name in result:
            raise AuthorityError("duplicate/non-basename provenance input")
        result[name] = _sha(row["sha256"])
    return result


def _recover(package_dir, evidence_root, control_pins, historical_audit_path, historical_audit_sha):
    """Private injection seam for tiny synthetic tests; public defaults cannot be overridden."""
    package, evidence = _plain(package_dir), _plain(evidence_root)
    _same(sorted(control_pins), sorted(CONTROL_PINS), "control pin inventory")
    tracked = {}
    controls = {}
    for relative, digest in control_pins.items():
        controls[relative] = _json(evidence / _relative(relative), digest)
        tracked[evidence / relative] = _identity(evidence / relative)
        _same(tracked[evidence / relative]["sha256"], digest, "control changed after JSON read")
    manifest, acceptance, provenance, audit = (controls[k] for k in (MANIFEST, ACCEPTANCE, PROVENANCE, AUDIT))
    _same(manifest["product_class"], PRODUCT_CLASS, "product class")
    _same(manifest["authoritative_scope"], SCOPE, "accepted scope")
    _same(manifest["coordinate_system"], COORDINATES, "coordinate frame")
    for key, value in SCOPE_STATUSES.items():
        _same(manifest[key], value, key)
    output_map = _pin_list(manifest["output_files"])
    source_map = _pin_list(manifest["source_files"], source=True)
    expected_sources = {f"{folder}/{name}" for name, (folder, _) in SOURCE_ROLES.items()}
    _same(sorted(source_map), sorted(expected_sources), "source inventory")
    _same(sorted(output_map), sorted(expected_sources | EXTRA_OUTPUTS), "output inventory")
    _same(manifest["output_file_count"], len(output_map), "output file count")
    for relative, row in output_map.items():
        identity = _identity(evidence / relative)
        _same((identity["sha256"], identity["bytes"]), (row["sha256"], row["bytes"]), f"packaged output {relative}")
        tracked[evidence / relative] = identity
    by_name = {row["source_path"]: row for row in source_map.values()}
    for relative, row in source_map.items():
        _same((row["sha256"], row["bytes"]), (output_map[relative]["sha256"], output_map[relative]["bytes"]), "source/output file binding")
    for relative, digest in control_pins.items():
        if relative != MANIFEST:
            _same(output_map[relative]["sha256"], digest, "promoted manifest control pin")
    accepted = acceptance["accepted_product"]
    _same(acceptance["checkpoint_id"], "CHECKPOINT1C", "acceptance checkpoint")
    _same(acceptance["decision"], "ACCEPTED", "acceptance decision")
    _same(accepted["product_class"], PRODUCT_CLASS, "accepted product class")
    _same(accepted["atlas_provenance_sha256"], control_pins[PROVENANCE], "accepted provenance")
    _same(accepted["independent_adversarial_audit_sha256"], control_pins[AUDIT], "accepted audit")
    _same(accepted["independent_scientific_validation_status"], "PASS", "accepted scientific validation")
    _same(accepted["accepted_manifest_sha256_before_status_promotion"], OLD_MANIFEST_SHA, "recorded old manifest pin")
    binding = manifest["user_acceptance_binding"]
    for key in ("record_id", "decision", "accepted_by", "recorded_utc"):
        _same(binding[key], acceptance[key], f"promoted acceptance {key}")
    _same(binding["record_path"], ACCEPTANCE, "acceptance record path")
    _same(binding["record_sha256"], control_pins[ACCEPTANCE], "acceptance record hash")
    _same(binding["accepted_manifest_sha256_before_status_promotion"], OLD_MANIFEST_SHA, "promoted old-manifest link")
    _same(binding["checkpoint2_eligible"], True, "recorded checkpoint 2 eligibility")
    _same(binding["checkpoint2_work_started"], False, "no checkpoint 2 execution")
    _same(acceptance["authorization"], {"next_checkpoint": "CHECKPOINT2", "macro_topography_stage_status": "ELIGIBLE",
                                     "topography_work_started_by_this_record": False}, "limited historical authorisation")
    _same(acceptance["scope_limits"], {
        "three_dimensional_framework_status": "DEFERRED", "categorical_reference_realization_status": "REVIEW_ONLY",
        "detailed_topography_stage_status": "BLOCKED", "hydrology_stage_status": "BLOCKED",
        "final_outcrop_status": "DEFERRED_UNTIL_TOPOGRAPHY_AND_EROSION", "terrain_generated": False,
        "hydrology_generated": False}, "acceptance exclusions")
    status = _json(evidence / STATUS, output_map[STATUS]["sha256"])
    for key, value in SCOPE_STATUSES.items():
        _same(status[key], value, f"status control {key}")
    for key in ("terrain_generated", "hydrology_generated", "checkpoint2_work_started", "package_old_3d_or_section_artifacts"):
        _same(status[key], False, f"status control {key}")
    _same(status["acceptance_record_id"], acceptance["record_id"], "status acceptance ID")
    _same(status["acceptance_record_sha256"], control_pins[ACCEPTANCE], "status acceptance hash")
    _same(status["accepted_manifest_sha256_before_status_promotion"], OLD_MANIFEST_SHA, "status old manifest")
    generated = _named_pins(provenance["outputs"])
    _same(sorted(generated), sorted(PROVENANCE_OUTPUTS), "provenance output inventory")
    for name, digest in generated.items():
        _same(digest, by_name[name]["sha256"], f"provenance output {name}")
    builder = provenance["builder"]
    _same(builder, {"path": "build_checkpoint1c_constraint_atlas.py",
                    "sha256": by_name["build_checkpoint1c_constraint_atlas.py"]["sha256"]}, "builder provenance")
    _same(audit["overall_status"], "PASS", "retained audit overall status")
    _same(audit["scientific_validation_status"], "PASS", "retained audit science status")
    _same(audit["blocking_codes"], [], "retained audit blockers")
    audited = audit["audited_artifact_hashes"]
    _same(sorted(audited), sorted(AUDITED_NAMES), "audited artifact inventory")
    for name, digest in audited.items():
        _same(digest, by_name[name]["sha256"], f"audited role {name}")
        _same(audit["metrics"]["audited_hashes"][name], digest, f"audit metrics role {name}")
    audit_binding = manifest["independent_audit_binding"]
    for key, value in (("present", True), ("status", "PASS"), ("current_hash_binding_required_for_pass", True)):
        _same(audit_binding[key], value, f"audit binding {key}")
    _same(audit_binding["audited_authoritative_source_names"], list(AUDITED_NAMES[:9]), "audited authoritative role mapping")
    inputs = _named_pins(provenance["inputs"])
    _same(list(inputs), list(HISTORY_INPUTS + OTHER_INPUTS), "exact provenance input order")
    history_bindings = []
    for name in HISTORY_INPUTS:
        old_audit = name == HISTORY_INPUTS[3]
        path = _plain(historical_audit_path) if old_audit else package / name
        identity = _identity(path)
        _same(identity["sha256"], inputs[name], f"History A input {name}")
        if old_audit:
            _same(identity["sha256"], historical_audit_sha, "historical audit hardpin")
            historical = _json(path, historical_audit_sha)
            _same(historical["overall_status"], "PASS", "historical audit status")
            _same(historical["promotion_authorized"], False, "historical non-promotion")
        tracked[path] = identity
        history_bindings.append({**identity, "logical_name": name,
                                 "binding_origin": "PINNED_RETAINED_HISTORICAL_AUDIT_NOT_R2_AUDIT" if old_audit else "SUPPLIED_R1_PACKAGE"})
    for path, identity in tracked.items():
        _same(_identity(path), identity, f"bound file changed during verification: {path}")
    return {
        "schema": "diadem.tectonics.c1c-recovered-scope.v1", "status": "PASS_EVIDENCE_CLOSURE",
        "scope": SCOPE, "product_class": PRODUCT_CLASS, "acceptance_decision": "ACCEPTED",
        "acceptance_record": {"path": str(evidence / ACCEPTANCE), "sha256": control_pins[ACCEPTANCE],
                              "record_id": acceptance["record_id"], "accepted_by": acceptance["accepted_by"]},
        "promoted_manifest": {"path": str(evidence / MANIFEST), "sha256": control_pins[MANIFEST]},
        "pre_promotion_manifest": {"recorded_sha256": OLD_MANIFEST_SHA, "links_agree": True,
                                   "historical_bytes_rehashed": False, "status": "RECORDED_LINK_ONLY"},
        "retained_scope_statuses": dict(SCOPE_STATUSES), "historical_scope_limits": acceptance["scope_limits"],
        "verified_output_file_count": len(output_map), "verified_source_file_count": len(source_map),
        "verified_files": [tracked[path] for path in sorted(tracked, key=str)],
        "history_a_bindings": history_bindings,
        "other_provenance_inputs_not_rehashed_by_this_scope": [{"path": name, "sha256": inputs[name]} for name in OTHER_INPUTS],
        "coordinate_relationship": {"c1c": COORDINATES,
                                    "history_a": {"axes": "x east/y south", "shape_rows_columns": [1651, 1951],
                                                  "sampling": "node samples x=0..1950, y=0..1650 km"},
                                    "coordinate_transform": "x_c1c=x_history_a; y_c1c=1650-y_history_a",
                                    "sampling_equivalence": False, "resampling_performed": False,
                                    "warning": "Coordinate reflection does not convert the node raster into cell-centred samples"},
        "history_a_wholesale_acceptance_established": False,
        "plate_identity": "NOT_ESTABLISHED_BY_THIS_EVIDENCE",
        "snapshot_motion": "NOT_ESTABLISHED_BY_THIS_EVIDENCE",
        "fresh_scientific_or_visual_audit_performed": False, "downstream_generation_performed": False,
        "inputs_unchanged": True, "category_complete": False, "production_authorized": False,
        "limits": ["Acceptance is confined to C1C continuous 2-D/2.5-D constraints and uncertainty",
                   "The retained independent audit is authenticated, not rerun or extended to parent History A",
                   "Four generated parents come from R1; its unchanged historical audit is bound separately",
                   "The pre-promotion manifest hash is a matching recorded link, not recovered/rehashed bytes",
                   "Only listed package members and the five stated History A parents are verified; no full upstream replay closure claim"],
    }


def recovered_scope(package_dir: Path) -> dict:
    """Verify fixed accepted C1C closure and the supplied matching History A package."""
    try:
        return _recover(package_dir, C1C_ROOT, CONTROL_PINS, LEGACY / HISTORY_INPUTS[3], HISTORY_AUDIT_SHA)
    except (KeyError, TypeError, OSError) as exc:
        raise AuthorityError(f"recovered C1C scope unavailable or malformed: {exc}") from exc
