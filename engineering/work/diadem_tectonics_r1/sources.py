"""Read-only, content-pinned History A *historical review replay* source gate.

This does not run the historical audit, decode scientific arrays, establish
current canon, or grant production authority. All reads are bounded/streamed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct

SOURCE_ROOT = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted")
REBUILD = "work/stage4-rebuild"
SHARED = f"{REBUILD}/checkpoint1-event-model-shared-manifest-review-only.json"
AUDIT = f"{REBUILD}/checkpoint1-history-a-audit.json"
CHECKPOINT0 = f"{REBUILD}/checkpoint0-frozen-inputs.json"
CONTRACT = f"{REBUILD}/checkpoint1-event-model-audit-contract-review-only.json"
BOOTSTRAP_PINS = {
    SHARED: "6026efa7e356af64c53a5f120876f2dd91508dd9c7ff0b9afe6901e069f9f146",
    AUDIT: "6900fe302774b8c7e4d754a15c0596857f9270e6cd1b2bf2186339388d3fbe9e",
    CHECKPOINT0: "f4a91c4bda4d55fc24c92aa07886c28ab14e4cdf9da6437cfb1790cbd7105b44",
}
MASTER = "outputs/Diadem_Geography_Master_Living_Canon.docx"
MASTER_ARCHIVE = "outputs/archive/Diadem_Geography_Master_Living_Canon_v0.31.docx"
MASTER_SHA256 = "1be937fc4c80169c7bcfd21a1d8e948da25cd92df075e702b2f7fc68e742d5e0"
ANCHOR = "work/stage4-review/peak-anchor-relaxation-analysis-review-only.json"
ANCHOR_SHA256 = "52311e9e9bef39ee6d46e156f598049c5f5999d217a30f18e1a68a7ea3d57aae"
COORDINATE_SHA256 = "22438121042615c837f9fb1d1a87c55567047316aad2b657b657700b6a2cf26d"
SOURCE_PATHS = [f"{REBUILD}/build_checkpoint1_history_a.py", CONTRACT,
                f"{REBUILD}/CHECKPOINT1_REPLACEMENT_STRUCTURAL_GEOLOGY_BLUEPRINT.md",
                f"{REBUILD}/CHECKPOINT1_ACCEPTANCE_RUBRIC.md"]
ARTIFACT_PATHS = {role: f"{REBUILD}/checkpoint1-history-a-{name}" for role, name in (
    ("events", "events.json"), ("faults_blocks", "faults-blocks.geojson"),
    ("provinces", "provinces.geojson"), ("accommodation", "accommodation.geojson"),
    ("sections", "sections.geojson"), ("structural_fields", "structural-fields.npz"),
    ("lineage", "lineage.json"), ("visual_manifest", "visual-manifest.json"),
    ("visual_review", "visual-review.json"))}
FROZEN_IDENTITIES = [
    (MASTER, "master_ledger", True),
    ("outputs/Diadem_Topographic_Foundation_Stage3C.json", "superseded_candidate_metadata", True),
    ("outputs/Diadem_Topographic_Foundation_Stage3C.npz", "superseded_candidate_arrays", True),
    ("outputs/Diadem_Physical_Terrain_Stage4_Candidate.json", "rejected_candidate_metadata", True),
    ("outputs/Diadem_Physical_Terrain_Stage4_Candidate.npz", "rejected_candidate_arrays", True),
    ("work/STAGE4_NONRADIAL_TERRAIN_CONTRACT.md", "active_contract", False),
    ("work/diagnose_stage4_ellipse_artifacts.py", "failure_diagnostic", False),
    (ANCHOR, "approved_anchor_decision_source", True),
]
ANCHOR_ORDER = "edelstein glanzgrund serenakrone moorwandler laubraunen verfuehrschlund buchhain sturmglas feuerschuppe wiedergeborene_flamme eisenweb nachtfluestern marienhain eremitenschale duftfaehrte zwielicht dunkelhauch frostglanz seelenwacht stillklinge".split()
VISUAL_ROLES = "plan_full_frame event_contribution_decomposition fault_block_vector_graph province_classes regional_zoom_gate regional_zoom_interior_accommodation regional_zoom_southern_arc regional_zoom_great_forest geological_sections legacy_approved_implemented_overlay process_only_control_comparison".split()
AUDIT_CODES = "AUDIT_CONTRACT CHECKPOINT0_AUTHORITY APPROVED_TRANSFER_REFERENCE_AUTHORITY SHARED_PACKAGE_MANIFEST SHARED_AUTHORITY_HASHES PRODUCTION_AND_MASTER_UNCHANGED HASH_BOUND_HISTORY_ARTIFACTS READABLE_HISTORY_PACKAGE EVENT_CHRONOLOGY VECTOR_PRIMARY_LAYER_INVENTORY NO_UNAPPROVED_EXTERNAL_APRON STRUCTURAL_DOMAIN_PARTITION_AND_RASTER_SCOPE FAULT_GRAPH_SCHEMA_AND_TOPOLOGY BLOCK_KINEMATIC_DERIVATION CROWN_GATE_AND_MASSIF_MODEL RASTER_SCHEMA_ZERO_SENTINEL_AND_SCOPE COMPLETE_NONRADIAL_LINEAGE_AND_RECONSTRUCTION ACCOMMODATION_GRAPH_AND_ARTIFICIAL_ISLAND_DEFERRAL STRUCTURALLY_COUPLED_PROVINCES TRUE_MAP_MATCHED_SECTIONS COMPLETE_VISUAL_EVIDENCE SELECTED_HISTORY_SCOPE EVERY_RETAINED_HISTORY_PASSES_A_TO_E READY_FOR_MICHAEL_CHECKPOINT_REVIEW".split()
MAX_JSON_BYTES = 16 * 1024 * 1024


class SourceGateError(RuntimeError):
    """Controlled malformed-source or failed required-gate exception."""


def _expect(actual, expected, label):
    if type(actual) is not type(expected) or actual != expected:
        raise SourceGateError(f"{label}: unexpected identity, schema or status")


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SourceGateError("Malformed SHA256 pin")
    return value


def _relative(value):
    if not isinstance(value, str) or not value or any(c in value for c in "\\:\x00<>|?*"):
        raise SourceGateError(f"Unsafe relative source path: {value!r}")
    parts = value.split("/")
    if any(not p or p in (".", "..") or p.rstrip(" .") != p or
           any(ord(c) < 32 for c in p) or
           re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
           for p in parts) or PurePosixPath(value).is_absolute():
        raise SourceGateError(f"Unsafe relative source path: {value!r}")
    return value


def _no_links(path):
    for item in (path, *path.parents):
        info = item.lstat()  # Deliberately checks dangling links, without resolve().
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SourceGateError(f"Symlink/reparse source path: {item}")


def _identity(info):
    # CPython 3.12 Windows lstat exposes creation time as ctime, while fstat
    # exposes NTFS change time. Compare birth time across APIs, and still check
    # each API's own ctime before/after below (do not discard mutation checks).
    stable_time = getattr(info, "st_birthtime_ns", info.st_ctime_ns) if os.name == "nt" else info.st_ctime_ns
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, stable_time)


def _api_identity(info):
    return (*_identity(info), info.st_ctime_ns)


def _json(raw, label):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SourceGateError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def invalid(value):
        raise SourceGateError(f"{label}: non-finite JSON number {value}")

    def number(value):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else invalid(value)

    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                           parse_constant=invalid, parse_float=number)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SourceGateError(f"{label}: malformed JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceGateError(f"{label}: expected JSON object")
    return value


class _Inspection:
    def __init__(self, root):
        self.root = root
        self.records = {}
        self.documents = {}
        self.observations = {}
        self.issues = []

    def check(self, relative, expected):
        relative, expected = _relative(relative), _sha(expected)
        if relative in self.records:
            _expect(self.records[relative]["expected_sha256"], expected, relative)
            return self.documents.get(relative)
        replacement = MASTER_ARCHIVE if relative == MASTER else relative
        if relative == MASTER:
            _expect(expected, MASTER_SHA256, "historical master identity")
        path = self.root / replacement
        record = {"relative_path": relative, "resolved_path": str(path),
                  "resolved_relative_path": replacement, "expected_sha256": expected,
                  "actual_sha256": None, "status": "BLOCKED"}
        if replacement != relative:
            record["resolution"] = "EXACT_HASH_PINNED_HISTORICAL_ARCHIVE"
        self.records[relative] = record
        raw = bytearray() if path.suffix.lower() in (".json", ".geojson") else None
        try:
            _no_links(path)
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                raise SourceGateError(f"Not a regular source file: {path}")
            if raw is not None and before.st_size > MAX_JSON_BYTES:
                raise SourceGateError(f"JSON source exceeds {MAX_JSON_BYTES} bytes: {path}")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(path, flags), "rb") as handle:
                before_fd = os.fstat(handle.fileno())
                if _identity(before_fd) != _identity(before):
                    raise SourceGateError(f"Source changed before read: {path}")
                digest = hashlib.sha256()
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    if raw is not None:
                        raw.extend(chunk)
                        if len(raw) > MAX_JSON_BYTES:
                            raise SourceGateError(f"JSON grew beyond its bound: {path}")
                after_fd = os.fstat(handle.fileno())
            _no_links(path)
            if _api_identity(before_fd) != _api_identity(after_fd) or _api_identity(before) != _api_identity(path.lstat()):
                raise SourceGateError(f"Source changed during read: {path}")
            record["actual_sha256"] = digest.hexdigest()
            record["status"] = "PASS" if digest.hexdigest() == expected else "HASH_MISMATCH"
            self.observations[relative] = (path, _api_identity(before), _api_identity(after_fd))
        except (OSError, SourceGateError) as exc:
            record["status"] = "MISSING" if isinstance(exc, FileNotFoundError) else "UNSAFE_OR_UNREADABLE"
            self.issues.append(f"{relative}: {exc}")
            return None
        if record["status"] != "PASS":
            self.issues.append(f"{relative}: SHA256 mismatch")
            return None
        # Parse only authenticated bytes, never re-open a JSON after hashing it.
        if raw is not None:
            self.documents[relative] = _json(raw, relative)
        return self.documents.get(relative)

    def finish(self):
        for relative, (path, identity, fd_identity) in self.observations.items():
            try:
                _no_links(path)
                if _api_identity(path.lstat()) != identity:
                    raise SourceGateError("Source changed during inspection")
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                with os.fdopen(os.open(path, flags), "rb") as handle:
                    if _api_identity(os.fstat(handle.fileno())) != fd_identity:
                        raise SourceGateError("Source handle identity changed during inspection")
                _no_links(path)
            except (OSError, SourceGateError) as exc:
                self.records[relative]["status"] = "CHANGED_DURING_INSPECTION"
                self.issues.append(f"{relative}: {exc}")
        passed = bool(self.records) and not self.issues
        return {"schema_version": 1, "status": "PASS" if passed else "BLOCKED",
                "scope": "HISTORICAL_HISTORY_A_REVIEW_REPLAY_ONLY",
                "review_replay_source_gate_passed": passed,
                "production_authority_established": False,
                "current_canon_authority_established": False,
                "historical_audit_reexecuted": False, "fresh_scientific_tests_run": 0,
                "files": list(self.records.values()), "issues": self.issues}


def _validate(gate, shared, audit, checkpoint):
    for key, value in {"schema_version": "1.0-review", "checkpoint": "checkpoint-1-structural-geology",
                       "status": "REVIEW_ONLY_NOT_ACCEPTED", "production_unchanged": True,
                       "master_ledger_unchanged": True}.items():
        _expect(shared[key], value, f"shared.{key}")
    _expect(list(shared["histories"]), ["A", "B"], "history inventory")
    _expect(shared["histories"]["A"]["status"], "selected_under_review", "History A status")
    _expect(shared["histories"]["B"], {"status": "not_selected_before_implementation", "artifacts": {}}, "History B")
    authority = shared["authority"]
    for key, value in {"checkpoint0_manifest_sha256": BOOTSTRAP_PINS[CHECKPOINT0],
                       "approved_coordinate_sha256": COORDINATE_SHA256,
                       "anchor_source_review_sha256": ANCHOR_SHA256,
                       "selected_history": "A", "selection_verbatim": "I choose A"}.items():
        _expect(authority[key], value, f"shared.authority.{key}")
    _expect([p["path"] for p in shared["generator_sources"]], SOURCE_PATHS, "four generator identities")
    for pin in shared["generator_sources"]:
        gate.check(pin["path"], pin["sha256"])
    artifacts = shared["histories"]["A"]["artifacts"]
    _expect(list(artifacts), list(ARTIFACT_PATHS), "nine artifact roles")
    for role, relative in ARTIFACT_PATHS.items():
        _expect(artifacts[role]["path"], relative, f"{role} path")
        gate.check(relative, artifacts[role]["sha256"])
    if gate.issues:
        return
    contract = gate.documents[CONTRACT]
    for key, value in {"schema_version": "1.0.0-review", "status": "active_fail_closed_audit_contract",
                       "checkpoint": "checkpoint-1-structural-geology", "production_authority": False,
                       "selected_history": "a"}.items():
        _expect(contract[key], value, f"contract.{key}")
    _expect(contract["history_selection"]["approval_verbatim"], "I choose A", "selection")
    _expect(contract["history_selection"]["history_b_status"], "not_selected_before_implementation", "unselected history")
    _expect(contract["authority"]["checkpoint0_manifest"], {"path": CHECKPOINT0, "sha256": BOOTSTRAP_PINS[CHECKPOINT0]}, "contract checkpoint0")
    _expect(contract["authority"]["anchor_source_review"], {"path": ANCHOR, "sha256": ANCHOR_SHA256}, "contract anchor source")
    _expect(contract["authority"]["approved_coordinate_sha256"], COORDINATE_SHA256, "contract coordinates")
    _expect(contract["required_visual_roles"], VISUAL_ROLES, "eleven visual roles")
    _expect(checkpoint["schema_version"], "1.0.0", "checkpoint schema")
    for key, value in {"id": "checkpoint-0", "name": "frozen-inputs", "status": "accepted",
                       "promotion_authorized": False, "next_checkpoint": "checkpoint-1-structural-geology"}.items():
        _expect(checkpoint["checkpoint"][key], value, f"checkpoint.{key}")
    freeze = checkpoint["file_freeze_snapshot"]
    _expect(freeze["hash_algorithm"], "sha256", "freeze hash algorithm")
    _expect([p["path"] for p in freeze["files"]], [x[0] for x in FROZEN_IDENTITIES], "eight frozen identities")
    for pin, (relative, role, unchanged) in zip(freeze["files"], FROZEN_IDENTITIES):
        _expect(pin["role"], role, "freeze role")
        _expect(pin["must_remain_unchanged_until_checkpoint1_review"], unchanged, "freeze status")
        gate.check(relative, pin["sha256"])
    _expect(checkpoint["authority"]["master_ledger"]["path"], MASTER, "master declared path")
    _expect(checkpoint["authority"]["master_ledger"]["sha256"], MASTER_SHA256, "master pin")
    _expect(checkpoint["authority"]["master_ledger"]["version"], "0.31", "master version")
    gate.check(ANCHOR, ANCHOR_SHA256)
    peak = checkpoint["peak_anchors"]
    _expect(peak["status"], "approved_transfer_zone_resegmentation_macro_reference", "anchor status")
    _expect(peak["clockwise_order_from_north_west_gate_flank"], ANCHOR_ORDER, "anchor order")
    _expect(peak["decision_provenance"]["ordered_coordinate_sha256"], COORDINATE_SHA256, "anchor coordinate pin")
    _expect(peak["decision_provenance"]["source_review_sha256"], ANCHOR_SHA256, "anchor review pin")
    anchors = peak["anchors"]
    _expect(sorted(a["haus"] for a in anchors), sorted(ANCHOR_ORDER), "twenty unique anchors")
    by_name = {a["haus"]: a for a in anchors}
    packed = bytearray()
    for name in ANCHOR_ORDER:
        anchor = by_name[name]
        _expect(anchor["unit"], "km", "anchor unit")
        _expect(anchor["status"], "approved_macro_anchor", "anchor status")
        for key in ("x", "y"):
            value = anchor[key]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise SourceGateError("Non-numeric/non-finite anchor coordinate")
            packed.extend(struct.pack("<d", value))
    _expect(hashlib.sha256(packed).hexdigest(), COORDINATE_SHA256, "computed coordinate hash")
    for key, value in {"schema_version": "1.0.0-review", "audit": "checkpoint1-event-model-independent-fail-closed",
                       "overall_status": "PASS", "promotion_authorized": False,
                       "fail_closed": True, "histories_audited": ["a"]}.items():
        _expect(audit[key], value, f"historical audit.{key}")
    _expect(audit["contract"]["path"], str(SOURCE_ROOT / CONTRACT), "audit original contract path")
    _expect(audit["contract"]["sha256"], gate.records[CONTRACT]["expected_sha256"], "audit contract pin")
    _expect([check["code"] for check in audit["checks"]], AUDIT_CODES, "24 historical check identities")
    for check in audit["checks"]:
        _expect(check["status"], "PASS", f"historical {check['code']}")
    for key, value in {"pass_count": 24, "fail_count": 0, "blocking_codes": [],
                       "checkpoint2_status": "eligible_only_after_michael_checkpoint_acceptance"}.items():
        _expect(audit["summary"][key], value, f"historical summary.{key}")
    visual = gate.documents[ARTIFACT_PATHS["visual_manifest"]]
    review = gate.documents[ARTIFACT_PATHS["visual_review"]]
    for document, status in ((visual, "COMPLETE_AWAITING_INDEPENDENT_REVIEW"), (review, "PASS")):
        _expect(document["schema_version"], "1.0-review", "visual schema")
        _expect(document["history"], "A", "visual history")
        _expect(document["status"], status, "visual status")
    _expect(review["reviewer_role"], "independent", "historical reviewer")
    _expect([a["role"] for a in visual["artifacts"]], VISUAL_ROLES, "visual artifact inventory")
    _expect([a["role"] for a in review["items"]], VISUAL_ROLES, "visual review inventory")
    for item in review["items"]:
        _expect(item["status"], "PASS", "historical visual item")
    for pin in visual["artifacts"]:
        _expect(pin["path"], f"{REBUILD}/checkpoint1-history-a-{pin['role'].replace('_', '-')}-review-only.png", "visual filename")
        gate.check(pin["path"], pin["sha256"])


def inspect_sources(root=SOURCE_ROOT):
    """Return PASS/BLOCKED; malformed authenticated documents raise SourceGateError."""
    try:
        raw_root = str(root)
        if raw_root.replace("/", "\\").startswith(("\\\\?\\", "\\\\.\\")):
            raise SourceGateError("Device/extended source root is forbidden")
        root = Path(root)
        if not root.is_absolute() or ".." in root.parts:
            raise SourceGateError("Source root must be an absolute, non-escaping path")
        _no_links(root)
        if not root.is_dir():
            raise SourceGateError("Source root is not a directory")
    except (OSError, SourceGateError, TypeError, ValueError) as exc:
        gate = _Inspection(Path("."))
        gate.issues.append(f"Invalid source root: {exc}")
        return gate.finish()
    gate = _Inspection(root)
    try:
        shared, audit, checkpoint = [gate.check(path, BOOTSTRAP_PINS[path]) for path in (SHARED, AUDIT, CHECKPOINT0)]
        if not gate.issues:
            _validate(gate, shared, audit, checkpoint)
    except SourceGateError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, struct.error) as exc:
        raise SourceGateError(f"Malformed source document: {exc}") from exc
    return gate.finish()


def require_sources(root=SOURCE_ROOT):
    result = inspect_sources(root)
    if not result["review_replay_source_gate_passed"]:
        raise SourceGateError("Historical review replay source gate BLOCKED: " + "; ".join(result["issues"]))
    return result
