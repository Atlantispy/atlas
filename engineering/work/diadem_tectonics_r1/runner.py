"""Isolated Diadem History A review replay; never a production entry point."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time

import sources
from compare import compare_products


ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT.parents[1] / "outputs" / "diadem-tectonics-review-r1"
INPUT_NAMES = (
    "build_checkpoint1_history_a.py", "checkpoint0-frozen-inputs.json",
    "checkpoint1-event-model-audit-contract-review-only.json",
    "CHECKPOINT1_REPLACEMENT_STRUCTURAL_GEOLOGY_BLUEPRINT.md",
    "CHECKPOINT1_ACCEPTANCE_RUBRIC.md",
)
PREFIX = "checkpoint1-history-a-"
STATIC_PRODUCTS = {
    PREFIX + suffix for suffix in (
        "events.json", "faults-blocks.geojson", "provinces.geojson",
        "accommodation.geojson", "sections.geojson", "structural-fields.npz",
        "lineage.json", "visual-manifest.json", "visual-review.json",
        "vector-skeleton-preview.png", "evidence-contact-sheet-review-only.jpg",
    )
} | {"checkpoint1-event-model-shared-manifest-review-only.json"}
PENDING_REVIEW_NOTES = "Complete evidence rendered; awaiting independent adversarial review."
CONTRACT_KEYS = set("schema_version status checkpoint production_authority selected_history history_selection authority shared_manifest_filename shared_manifest_required_keys history_artifact_filename_templates required_events faults_blocks_layers required_fault_properties required_block_properties required_structural_model_domain_properties structural_model_domain_contract fault_block_raster_contract required_crown_link_properties required_massif_properties allowed_node_types required_crown_system_ids required_titan_component_ids required_master_domain_ids allowed_master_domain_ids required_npz_arrays required_accommodation_layers required_accommodation_compartment_properties required_accommodation_ids required_accommodation_edges required_province_ids required_province_properties required_section_ids required_section_layers section_display_contract required_visual_roles hard_thresholds forbidden_lineage_tokens forbidden_downstream_tokens artificial_island_policy audit_rule".split())
SHARED_KEYS = {"schema_version", "checkpoint", "status", "authority", "histories",
               "generator_sources", "production_unchanged", "master_ledger_unchanged"}


class ReplayError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_links(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ReplayError(f"linked/reparse path is not permitted: {part}")


def confined_output(path: Path) -> Path:
    raw = str(path).replace("\\", "/")
    if raw.startswith("//") or ".." in raw.split("/"):
        raise ReplayError("output must be a plain local path without traversal")
    allowed = Path(os.path.abspath(OUTPUT_ROOT))
    target = Path(os.path.abspath(path))
    if target == allowed or not target.is_relative_to(allowed):
        raise ReplayError(f"output must be a new child beneath {allowed}")
    reject_links(target)
    if target.exists():
        raise ReplayError(f"refusing to overwrite existing output: {target}")
    return target


def write_new(path: Path, payload: bytes) -> None:
    reject_links(path)
    with path.open("xb") as stream:
        stream.write(payload)


def write_json(path: Path, value: object) -> None:
    write_new(path, json.dumps(value, indent=2, ensure_ascii=False,
                               allow_nan=False).encode("utf-8"))


def read_json(path: Path, expected_sha256: str | None = None) -> dict:
    """Strict bounded parsing of the same bytes that are optionally hash-bound."""
    reject_links(path)
    with path.open("rb") as stream:
        payload = stream.read(sources.MAX_JSON_BYTES + 1)
    if len(payload) > sources.MAX_JSON_BYTES:
        raise ReplayError(f"JSON document exceeds size bound: {path}")
    if expected_sha256 is not None and hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ReplayError(f"JSON input changed before parsing: {path}")
    try:
        return sources._json(payload, str(path))
    except sources.SourceGateError as exc:
        raise ReplayError(str(exc)) from exc


def exact_keys(value, keys, label: str) -> None:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ReplayError(f"{label}: exact metadata key inventory differs")


def exact_value(value, expected, label: str) -> None:
    # Canonical JSON distinguishes booleans, integers and floating-point values;
    # ordinary Python dictionary equality would accept False == 0.
    if json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
        raise ReplayError(f"{label}: metadata identity/status differs")


def expected_authority() -> dict:
    return {"checkpoint0_manifest_sha256": sources.BOOTSTRAP_PINS[sources.CHECKPOINT0],
            "approved_coordinate_sha256": sources.COORDINATE_SHA256,
            "anchor_source_review_sha256": sources.ANCHOR_SHA256,
            "selected_history": "A", "selection_verbatim": "I choose A"}


def validate_contract(contract: dict) -> list[str]:
    """Check scope/control identities; full scientific rules remain byte-pinned inputs."""
    exact_keys(contract, CONTRACT_KEYS, "audit contract")
    for key, value in {"schema_version": "1.0.0-review", "status": "active_fail_closed_audit_contract",
                       "checkpoint": "checkpoint-1-structural-geology", "production_authority": False,
                       "selected_history": "a"}.items():
        exact_value(contract[key], value, f"audit contract {key}")
    exact_value(contract["history_selection"], {
        "decision_date": "2026-07-16", "decision_maker": "Michael", "approval_verbatim": "I choose A",
        "history_b_status": "not_selected_before_implementation"}, "contract history selection")
    exact_value(contract["authority"], {
        "checkpoint0_manifest": {"path": sources.CHECKPOINT0, "sha256": sources.BOOTSTRAP_PINS[sources.CHECKPOINT0]},
        "approved_anchor_option": "transfer_zone_resegmentation",
        "approved_coordinate_order": "peak_anchors.clockwise_order_from_north_west_gate_flank",
        "approved_coordinate_hash_method": "sha256 of clockwise-order x,y pairs as little-endian float64 C-order bytes",
        "approved_coordinate_sha256": sources.COORDINATE_SHA256,
        "anchor_source_review": {"path": sources.ANCHOR, "sha256": sources.ANCHOR_SHA256},
        "anchor_role": "regional Peak-seat reference and containment target only; never summit, structural centroid, Crown endpoint, fault node, divide point, kernel centre or elevation control",
    }, "contract authority")
    exact_value(contract["shared_manifest_filename"], Path(sources.SHARED).name, "contract shared filename")
    exact_value(contract["shared_manifest_required_keys"], [
        "schema_version", "checkpoint", "status", "authority", "histories", "generator_sources",
        "production_unchanged", "master_ledger_unchanged"], "contract shared keys")
    exact_value(contract["required_visual_roles"], sources.VISUAL_ROLES, "contract visual roles")
    return contract["required_visual_roles"]


def validate_pin(pin, *, visual: bool = False) -> None:
    exact_keys(pin, {"path", "sha256", "role"} if visual else {"path", "sha256"}, "candidate hash pin")
    if not isinstance(pin["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is None:
        raise ReplayError("candidate SHA256 pin is malformed")


def source_fingerprint(report: dict) -> dict[str, str]:
    return {item["resolved_path"]: item["actual_sha256"] for item in report["files"]}


def copy_verified(source: Path, destination: Path, expected: str) -> None:
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ReplayError(f"input changed while staging: {source}")
    write_new(destination, payload)
    if sha256(destination) != expected:
        raise ReplayError(f"staged input readback mismatch: {destination}")


def runtime_info() -> dict:
    import numpy
    import PIL
    fonts = [Path("C:/Windows/Fonts") / name for name in
             ("arial.ttf", "arialbd.ttf", "calibri.ttf", "calibrib.ttf")]
    return {"python": platform.python_version(), "python_build": sys.version,
            "executable": sys.executable, "platform": platform.platform(),
            "numpy": numpy.__version__, "pillow": PIL.__version__,
            "available_renderer_fonts": {str(path): sha256(path) for path in fonts if path.is_file()},
            "historical_runtime_identity": "NOT_RECOVERED",
            "validation": "CURRENT_RUNTIME_REQUIRES_EXACT_LOGICAL_PARITY"}


def expected_products(roles: list[str]) -> set[str]:
    if not isinstance(roles, list) or not roles or any(not isinstance(role, str) for role in roles):
        raise ReplayError("visual roles must be a nonempty string list")
    if len(roles) != len(set(roles)):
        raise ReplayError("visual role inventory is empty or duplicated")
    if any(not role or any(char not in "abcdefghijklmnopqrstuvwxyz_" for char in role)
           for role in roles):
        raise ReplayError("unsafe visual role")
    return STATIC_PRODUCTS | {PREFIX + role.replace("_", "-") + "-review-only.png"
                              for role in roles}


def validate_package(sandbox: Path, roles: list[str]) -> list[dict]:
    package = sandbox / sources.REBUILD
    expected = {str(Path(sources.REBUILD) / name).replace("\\", "/")
                for name in set(INPUT_NAMES) | expected_products(roles)}
    actual = set()
    for path in sandbox.rglob("*"):
        reject_links(path)
        if path.is_file():
            actual.add(path.relative_to(sandbox).as_posix())
    if actual != expected:
        raise ReplayError(f"unexpected package inventory: missing={sorted(expected-actual)}, "
                          f"extra={sorted(actual-expected)}")
    contract = read_json(package / INPUT_NAMES[2])
    exact_value(roles, validate_contract(contract), "passed/candidate contract visual roles")
    review = read_json(package / (PREFIX + "visual-review.json"))
    exact_value(review, {
        "schema_version": "1.0-review", "history": "A", "status": "PENDING",
        "reviewer_role": "pending_independent", "items": [
            {"role": role, "status": "PENDING", "notes": PENDING_REVIEW_NOTES} for role in roles],
    }, "replay must not inherit a historical visual PASS or alter pending review controls")
    shared = read_json(package / "checkpoint1-event-model-shared-manifest-review-only.json")
    exact_keys(shared, SHARED_KEYS, "shared manifest")
    for key, value in {"schema_version": "1.0-review", "checkpoint": "checkpoint-1-structural-geology",
                       "status": "REVIEW_ONLY_NOT_ACCEPTED", "production_unchanged": True,
                       "master_ledger_unchanged": True}.items():
        exact_value(shared[key], value, f"shared {key}")
    # These two historical booleans are format checks only. The fresh pre/post
    # source gates, not a producer's self-declaration, establish preservation.
    exact_value(shared["authority"], expected_authority(), "shared authority")
    exact_keys(shared["histories"], {"A", "B"}, "shared histories")
    exact_keys(shared["histories"]["A"], {"status", "artifacts"}, "History A controls")
    exact_value(shared["histories"]["A"]["status"], "selected_under_review", "History A status")
    exact_value(shared["histories"]["B"], {"status": "not_selected_before_implementation", "artifacts": {}}, "History B controls")
    exact_keys(shared["histories"]["A"]["artifacts"], sources.ARTIFACT_PATHS, "shared artifacts")
    for role, relative in sources.ARTIFACT_PATHS.items():
        validate_pin(shared["histories"]["A"]["artifacts"][role])
        if shared["histories"]["A"]["artifacts"][role]["path"] != relative:
            raise ReplayError(f"shared artifact role/path mismatch: {role}")
    if not isinstance(shared["generator_sources"], list):
        raise ReplayError("shared source inventory differs")
    for item in shared["generator_sources"]:
        validate_pin(item)
    actual_source_paths = [item["path"] for item in shared["generator_sources"]]
    if actual_source_paths != sources.SOURCE_PATHS:
        raise ReplayError("shared source inventory differs")
    visual = read_json(package / (PREFIX + "visual-manifest.json"))
    exact_keys(visual, {"schema_version", "history", "status", "artifacts"}, "visual manifest")
    for key, value in {"schema_version": "1.0-review", "history": "A",
                       "status": "COMPLETE_AWAITING_INDEPENDENT_REVIEW"}.items():
        exact_value(visual[key], value, f"visual {key}")
    if not isinstance(visual["artifacts"], list):
        raise ReplayError("visual artifact inventory differs")
    for item in visual["artifacts"]:
        validate_pin(item, visual=True)
    if [item["role"] for item in visual["artifacts"]] != roles:
        raise ReplayError("visual manifest role inventory differs")
    for item in visual["artifacts"]:
        relative = f"{sources.REBUILD}/{PREFIX}{item['role'].replace('_', '-')}-review-only.png"
        if item["path"] != relative:
            raise ReplayError(f"visual role/path mismatch: {item['role']}")
    pinned = [*shared["histories"]["A"]["artifacts"].values(),
              *shared["generator_sources"], *visual["artifacts"]]
    for item in pinned:
        relative = item["path"]
        if relative not in expected or sha256(sandbox / relative) != item["sha256"]:
            raise ReplayError(f"candidate manifest hash/path mismatch: {relative}")
    if sources.BOOTSTRAP_PINS[sources.CHECKPOINT0] != sha256(package / INPUT_NAMES[1]):
        raise ReplayError("candidate checkpoint0 binding differs")
    return [{"path": relative, "bytes": (sandbox / relative).stat().st_size,
             "sha256": sha256(sandbox / relative)} for relative in sorted(actual)]


def _execute_legacy(script: Path, sandbox: Path) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-I", "-B", str(ROOT / "child_guard.py"),
                           "--write-root", str(sandbox.parent), "--script", str(script)], cwd=sandbox,
                          env=environment, capture_output=True, text=True,
                          encoding="utf-8", errors="strict", timeout=300,
                          check=False, shell=False)


def replay_review(destination: Path) -> dict:
    target = confined_output(destination)
    before = sources.require_sources()
    runtime = runtime_info()
    engineering_before = {name: sha256(ROOT / name) for name in
                          ("runner.py", "sources.py", "compare.py", "child_guard.py")}
    pins = {item["relative_path"]: item for item in before["files"]}
    input_pins = {name: pins[f"{sources.REBUILD}/{name}"] for name in INPUT_NAMES}
    contract = read_json(Path(input_pins[INPUT_NAMES[2]]["resolved_path"]),
                         input_pins[INPUT_NAMES[2]]["expected_sha256"])
    roles = validate_contract(contract)
    expected_products(roles)
    # Recheck immediately before creating anything. Source gates never fall back.
    if source_fingerprint(sources.require_sources()) != source_fingerprint(before):
        raise ReplayError("source identity changed before staging")
    confined_output(target)
    target.mkdir(parents=True, exist_ok=False)
    sandbox = target / "sandbox"
    package = sandbox / sources.REBUILD
    failure = None
    result = None
    post_error = None
    elapsed = 0.0
    try:
        write_json(target / "sources-before.json", before)
        write_json(target / "runtime.json", runtime)
        package.mkdir(parents=True)
        for name, pin in input_pins.items():
            copy_verified(Path(pin["resolved_path"]), package / name, pin["expected_sha256"])
        start = time.perf_counter()
        result = _execute_legacy(package / INPUT_NAMES[0], sandbox)
        elapsed = time.perf_counter() - start
        if result.returncode != 0:
            raise ReplayError(f"isolated legacy replay failed ({result.returncode}); logs retained")
        for name, pin in input_pins.items():
            if sha256(package / name) != pin["expected_sha256"]:
                raise ReplayError(f"staged input changed during execution: {name}")
        files = validate_package(sandbox, roles)
        comparison = compare_products(sources.SOURCE_ROOT / sources.REBUILD, package)
        write_json(target / "logical-comparison.json", comparison)
        if comparison["status"] != "PASS":
            raise ReplayError("logical replay differs from retained History A; comparison retained")
        if {name: sha256(ROOT / name) for name in engineering_before} != engineering_before:
            raise ReplayError("engineering runner changed during verification")
    except BaseException as exc:
        failure = exc
    finally:
        def log_bytes(value):
            return value if isinstance(value, bytes) else (value or "").encode("utf-8")
        stdout = result.stdout if result is not None else getattr(failure, "stdout", None)
        stderr = result.stderr if result is not None else getattr(failure, "stderr", None)
        try:
            write_new(target / "stdout.log", log_bytes(stdout))
            write_new(target / "stderr.log", log_bytes(stderr))
        except Exception as exc:
            failure = failure or exc
        # Runs even for staging/launch/timeout errors, and after comparison.
        try:
            after = sources.require_sources()
            write_json(target / "sources-after.json", after)
            if source_fingerprint(after) != source_fingerprint(before):
                raise ReplayError("protected source or reference identity changed during replay/checks")
        except Exception as exc:
            post_error = str(exc)
            failure = failure or exc
        if failure is not None:
            write_json(target / "REPLAY_FAILURE.json", {
                "status": "FAILED_OR_BLOCKED", "error_type": type(failure).__name__,
                "error": str(failure), "post_source_check_attempted": True,
                "post_source_check_error": post_error,
                "production_authority_established": False,
            })
    if failure is not None:
        if not isinstance(failure, Exception):
            raise failure
        raise ReplayError(str(failure)) from failure
    report = {
        "status": "PASS_REVIEW_REPLAY_ONLY", "edition": "DIADEM",
        "stage": "history_a_structural_state", "source_status": "REVIEW_ONLY_NOT_ACCEPTED",
        "production_authority_established": False, "generator_1_0_complete": False,
        "fresh_historical_24_gate_audit": False, "visual_review": "PENDING",
        "visual_or_image_byte_parity_claimed": False,
        "original_source_hashes_unchanged": True,
        "legacy_nonmutation_flags_used_as_evidence": False,
        "child_write_guard": "PYTHON_AUDIT_HOOK_PLUS_VERIFIED_SOURCE_PATH_REBASING",
        "elapsed_seconds": elapsed, "runtime": runtime,
        "engineering_source_hashes": engineering_before,
        "source_fingerprint": source_fingerprint(before),
        "product_count": len(expected_products(roles)), "files": files,
        "logical_comparison": "logical-comparison.json",
        "limits": ["Relative structural state, not modern terrain or independently identified tectonic plates",
                   "No plate motion vectors, History B, downstream generation or canon promotion",
                   "The Python audit write guard supplements reviewed pinned code; it is not an OS sandbox for hostile native code",
                   "Historical runtime was not recovered; current runtime is checked against retained logical outputs",
                   "Executable independent historical auditor and later checkpoint acceptance are not established here"],
    }
    # Completion receipt is last. Failed runs retain evidence but no PASS receipt.
    write_json(target / "REPLAY_REPORT.json", report)
    return {"status": report["status"], "output": str(target),
            "report_sha256": sha256(target / "REPLAY_REPORT.json"),
            "product_count": report["product_count"], "elapsed_seconds": elapsed,
            "production_authority_established": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    replay = commands.add_parser("replay-review")
    replay.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = sources.inspect_sources() if args.command == "preflight" else replay_review(args.output)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0 if result["status"] in {"PASS", "PASS_REVIEW_REPLAY_ONLY"} else 2
    except (sources.SourceGateError, ReplayError, OSError, ValueError,
            subprocess.SubprocessError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc),
                          "production_authority_established": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
