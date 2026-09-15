"""Diadem tectonics review-stage assembly; no implicit canon or production mode."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parent
R1_ROOT = ROOT.parent / "diadem_tectonics_r1"
sys.path.insert(0, str(R1_ROOT))
import runner as replay
import sources
from child_guard import plain_local_path, reject_links
from compare import compare_products

from audit import audit_package
from authority import recovered_scope
from snapshot import build_snapshot

OUTPUT_ROOT = ROOT.parents[1] / "outputs" / "diadem-tectonics-stage-r2"
CODE_NAMES = ("stage.py", "audit.py", "geometry_audit.py", "snapshot.py", "authority.py")
PRODUCT_NAMES = {"tectonic-structural-domain-crosswalk.geojson",
                 "tectonic-fault-relationships.geojson", "tectonic-snapshot-motion.json"}


class StageError(RuntimeError):
    pass


def file_hash(path: Path) -> str:
    return replay.sha256(path)


def code_identity() -> dict:
    return {name: file_hash(ROOT / name) for name in CODE_NAMES}


def runtime_identity() -> dict:
    import numpy
    import shapely
    return {"python": platform.python_version(), "executable": sys.executable,
            "numpy": numpy.__version__, "shapely": shapely.__version__,
            "role": "INDEPENDENT_AUDIT_AND_SNAPSHOT_ONLY_NOT_LEGACY_REPLAY"}


def confined_new_output(path: Path) -> Path:
    target = plain_local_path(path)
    allowed = plain_local_path(OUTPUT_ROOT, absolute=True)
    reject_links(target)
    if target == allowed or not target.is_relative_to(allowed):
        raise StageError(f"output must be a new child of {allowed}")
    if target.exists():
        raise StageError("existing stage output is never overwritten")
    return target


def bind_json(path: Path | None) -> tuple[dict | None, dict | None]:
    if path is None:
        return None, None
    path = plain_local_path(path, absolute=True)
    reject_links(path)
    digest = file_hash(path)
    value = replay.read_json(path, digest)
    return value, {"path": str(path), "sha256": digest}


def bind_decision_sources(decisions: dict | None) -> list[dict]:
    """Verify exact supplied source bytes, not the truth of approval claims."""
    if decisions is None:
        return []
    refs = decisions.get("source_refs", [])
    if not isinstance(refs, list):
        raise StageError("decision source_refs must be a list")
    result = []
    for item in refs:
        if not isinstance(item, dict):
            raise StageError("decision source reference must be an object")
        path = plain_local_path(item.get("path"), absolute=True)
        reject_links(path)
        if not isinstance(item.get("locator"), str) or not item["locator"].strip():
            raise StageError("decision source needs an exact nonblank locator")
        digest = file_hash(path)
        if digest != item.get("sha256"):
            raise StageError(f"decision source changed: {path}")
        result.append({"id": item.get("id"), "path": str(path), "sha256": digest,
                       "locator": item["locator"], "authority_claim_verified": False})
    return result


def verify_structure_run(run_root: Path) -> tuple[Path, dict]:
    root = plain_local_path(run_root, absolute=True)
    reject_links(root)
    if not root.is_relative_to(replay.OUTPUT_ROOT) or root == replay.OUTPUT_ROOT:
        raise StageError("structural input must be an isolated R1 review run")
    report_path = root / "REPLAY_REPORT.json"
    report_hash = file_hash(report_path)
    report = replay.read_json(report_path, report_hash)
    if (report.get("status") != "PASS_REVIEW_REPLAY_ONLY" or
        report.get("production_authority_established") is not False or
        report.get("source_status") != "REVIEW_ONLY_NOT_ACCEPTED"):
        raise StageError("structural input has incompatible review/authority status")
    expected_code = {name: file_hash(R1_ROOT / name) for name in
                     ("runner.py", "sources.py", "compare.py", "child_guard.py")}
    if report.get("engineering_source_hashes") != expected_code:
        raise StageError("structural replay receipt is not bound to current verified R1 code")
    package = root / "sandbox" / sources.REBUILD
    inventory = replay.validate_package(root / "sandbox", sources.VISUAL_ROLES)
    if report.get("files") != inventory:
        raise StageError("structural package differs from its completed replay receipt")
    return package, {"root": str(root), "report_sha256": report_hash,
                     "files": inventory, "engineering_source_hashes": expected_code}


def audit_status(audit: dict) -> str:
    value = audit.get("overall_status", audit.get("status"))
    if value not in {"PASS", "FAIL", "BLOCKED"}:
        raise StageError("auditor did not return an explicit PASS/FAIL/BLOCKED result")
    return value


def write_product(target: Path, name: str, value: dict) -> dict:
    if not isinstance(name, str) or name not in PRODUCT_NAMES or Path(name).name != name:
        raise StageError("snapshot product name is not in the exact output contract")
    if any(char in name for char in ("/", "\\", ":")) or name in {".", ".."}:
        raise StageError("unsafe snapshot product name")
    path = target / name
    replay.write_json(path, value)
    return {"path": name, "sha256": file_hash(path), "bytes": path.stat().st_size}


def build_review(run_root: Path, output: Path, *, decisions_path: Path | None = None,
                 visual_review_path: Path | None = None) -> dict:
    target = confined_new_output(output)
    before = sources.require_sources()
    package, parent_before = verify_structure_run(run_root)
    scope_before = recovered_scope(package)
    if scope_before.get("status") != "PASS_EVIDENCE_CLOSURE":
        raise StageError("accepted successor evidence closure did not pass")
    decisions, decision_pin = bind_json(decisions_path)
    _, visual_pin = bind_json(visual_review_path)
    decision_sources = bind_decision_sources(decisions)
    implementation = code_identity()
    runtime = runtime_identity()
    # All pure preconditions are checked before creating a run directory.
    snapshot = build_snapshot(package, decisions)
    if not isinstance(snapshot.get("products"), dict) or set(snapshot["products"]) != PRODUCT_NAMES:
        raise StageError("snapshot builder returned an incompatible product inventory")
    confined_new_output(target)
    target.mkdir(parents=True, exist_ok=False)
    failure = None
    post_error = None
    try:
        replay.write_json(target / "sources-before.json", before)
        replay.write_json(target / "parent-before.json", parent_before)
        replay.write_json(target / "accepted-successor-scope-before.json", scope_before)
        replay.write_json(target / "runtime.json", runtime)
        if decisions is not None:
            replay.write_json(target / "supplied-domain-decisions.json", decisions)
        comparison = compare_products(sources.SOURCE_ROOT / sources.REBUILD, package)
        replay.write_json(target / "retained-logical-comparison.json", comparison)
        if comparison["status"] != "PASS":
            raise StageError("structural logical reference comparison failed")
        fresh_audit = audit_package(package, Path(parent_before["root"]), visual_review_path)
        science_status = audit_status(fresh_audit)
        replay.write_json(target / "independent-audit.json", fresh_audit)
        products = [write_product(target, name, payload)
                    for name, payload in sorted(snapshot["products"].items())]
        replay.write_json(target / "snapshot-validation.json", snapshot["validation"])
        if code_identity() != implementation:
            raise StageError("stage implementation changed during execution")
    except BaseException as exc:
        failure = exc
    finally:
        try:
            after = sources.require_sources()
            _, parent_after = verify_structure_run(run_root)
            scope_after = recovered_scope(package)
            replay.write_json(target / "sources-after.json", after)
            replay.write_json(target / "parent-after.json", parent_after)
            replay.write_json(target / "accepted-successor-scope-after.json", scope_after)
            if (replay.source_fingerprint(before) != replay.source_fingerprint(after) or
                parent_before != parent_after or scope_before != scope_after):
                raise StageError("protected sources or structural parent changed")
            for pin in (decision_pin, visual_pin):
                if pin and file_hash(Path(pin["path"])) != pin["sha256"]:
                    raise StageError("bound review/decision input changed")
            if bind_decision_sources(decisions) != decision_sources:
                raise StageError("domain evidence changed")
        except Exception as exc:
            post_error = str(exc)
            failure = failure or exc
        if failure is not None:
            replay.write_json(target / "STAGE_FAILURE.json", {
                "status": "FAILED_OR_BLOCKED", "error_type": type(failure).__name__,
                "error": str(failure), "post_checks_attempted": True,
                "post_check_error": post_error, "category_complete": False,
                "production_authorized": False})
    if failure is not None:
        if not isinstance(failure, Exception):
            raise failure
        raise StageError(str(failure)) from failure
    status = "INCOMPLETE_DOMAIN_AUTHORITY" if science_status == "PASS" else "BLOCKED_SCIENTIFIC_REVIEW"
    report = {
        "schema": "diadem.tectonics.review-stage.v2", "status": status,
        "engineering_assembly": "PASS", "independent_scientific_audit": science_status,
        "snapshot_validation": snapshot["validation"], "category_complete": False,
        "production_authorized": False, "source_status": "REVIEW_ONLY_NOT_ACCEPTED",
        "structural_parent": parent_before, "implementation_sha256": implementation,
        "runtime": runtime, "decision_input": decision_pin, "visual_review_input": visual_pin,
        "accepted_successor_scope": {
            "status": scope_before["status"], "scope_extended_by_this_run": False,
            "evidence_file": "accepted-successor-scope-before.json",
            "sha256": file_hash(target / "accepted-successor-scope-before.json")},
        "decision_sources": decision_sources, "protected_inputs_unchanged": True,
        "products": products,
        "limits": ["This review assembler does not grant domain approval or canon acceptance",
                   "Supplied source hashes establish identity, not the truth or scope of approval claims",
                   "Missing plate/motion decisions remain unknown, never invented or treated as zero",
                   "Fresh reconstructed audit is not the recovered historical executable auditor",
                   "History A contract findings do not automatically revoke later C1C reduced-scope acceptance",
                   "No downstream geology/terrain production is run or silently unlocked"],
    }
    # Publish the terminal receipt last. A partial write is never a report.
    try:
        pending = target / ".STAGE_REPORT.pending.json"
        replay.write_json(pending, report)
        report_digest = file_hash(pending)
        replay.read_json(pending, report_digest)
        pending.rename(target / "STAGE_REPORT.json")
    except BaseException as exc:
        try:
            replay.write_json(target / "STAGE_FAILURE.json", {
                "status": "FAILED_OR_BLOCKED", "error_type": type(exc).__name__,
                "error": str(exc), "post_checks_attempted": True,
                "post_check_error": None, "failure_phase": "final_report_publication",
                "category_complete": False, "production_authorized": False})
        except OSError:
            pass  # Disk failure can also prevent a receipt; never return PASS.
        if not isinstance(exc, Exception):
            raise
        raise StageError(str(exc)) from exc
    return {"status": status, "engineering_assembly": "PASS", "output": str(target),
            "report_sha256": report_digest,
            "products": len(products), "category_complete": False,
            "production_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structure-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain-decisions", type=Path)
    parser.add_argument("--visual-review", type=Path)
    args = parser.parse_args()
    try:
        result = build_review(args.structure_run, args.output,
                              decisions_path=args.domain_decisions,
                              visual_review_path=args.visual_review)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 2  # Review evidence may be assembled, but full stage is not approved.
    except (StageError, sources.SourceGateError, replay.ReplayError, OSError,
            ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAILED_OR_BLOCKED", "error": str(exc),
                          "category_complete": False, "production_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
