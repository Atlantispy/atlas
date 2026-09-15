from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from diadem_safety import PreRunSnapshotter
from diadem_safety.common import (
    PathSafetyError,
    SafetyError,
    atomic_write_json,
    canonical_json_bytes,
    is_reparse_or_symlink,
    make_read_only,
    reject_reparse_ancestors,
    reject_reparse_chain,
    sha256_bytes,
    sha256_file,
    validate_identifier,
    validate_relative_path,
)
from diadem_safety.recovery import RecoveryInspector


class GateError(RuntimeError):
    pass


MANIFEST_RELATIVE = "04_Manifests/drive_mirror_manifest.json"
GENERATOR_RELATIVE = "06_Generator_System"
TASKS = {
    "Validate": {
        "entry": "engine/validate_local_generator.py",
        "target": "LOCAL_GENERATOR_VALIDATION.json",
        "target_kind": "file",
    },
    "Smoke": {"entry": "engine/build_stage6c_100m.py", "target": None},
    "Full": {
        "entry": "engine/build_stage6c_100m.py",
        "target": "generated_outputs/Diadem_Province_Database_V4_STAGE6C_100M_SPATIAL_CONTEXT_WORKING_2026-08-30",
        "target_kind": "tree",
    },
    "BoundedReplay": {
        "entry": "engine/run_bounded_real_terrain_test.py",
        "target": "engine/bounded_real_terrain_test_2026-08-28",
        "target_kind": "tree",
    },
    "TileTests": {"entry": "engine/ten_m_tile_engine/tests", "target": None},
    "ExportTables": {
        "entry": "engine/export_analytical_tables.py",
        "target": "generated_outputs/Phase2_Analytical_Tables_STAGE6B_2026-08-29",
        "target_kind": "tree",
    },
    "FormatSupport": {
        "entry": "engine/verify_historical_format_support.py",
        "target": None,
    },
}
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "ABORTED"}
TASKS.update({
    "Refine10m": {"entry": "engine/build_stage6c5_10m.py", "target": None, "target_kind": "tree"},
    "Physical10m": {"entry": "engine/build_stage6c5r_physical_10m.py", "target": None, "target_kind": "tree"},
    "Population": {"entry": "engine/build_stage6d_population.py", "target": None, "target_kind": "tree"},
    "RuntimeTests": {"entry": "engine/tests", "target": None},
    "TerrainReference": {"entry": "engine/build_terrain_reference.py", "target": None, "target_kind": "tree"},
})


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([_norm(path), _norm(root)]) == _norm(root)
    except ValueError:
        return False


def _require_regular_root(path: Path, *, field: str) -> Path:
    path = path.expanduser().absolute()
    if not path.exists() or not path.is_dir():
        raise GateError(f"{field} is not an existing directory: {path}")
    reject_reparse_ancestors(path)
    return path


def _manifest_identity(workspace_root: Path) -> dict[str, str]:
    path = workspace_root / Path(MANIFEST_RELATIVE)
    reject_reparse_chain(workspace_root, path)
    if not path.is_file():
        raise GateError(f"Canonical schema-v2 manifest is missing: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("Canonical manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        raise GateError("Generator launch requires the schema-v2 baseline manifest")
    if value.get("manifest_kind") != "local_first_baseline":
        raise GateError("Canonical manifest_kind is not local_first_baseline")
    if value.get("snapshot_state") != "ready":
        raise GateError("Canonical baseline snapshot_state is not ready")
    baseline_id = value.get("baseline_id")
    if not isinstance(baseline_id, str) or not baseline_id:
        raise GateError("Canonical baseline_id is missing")
    return {"baseline_id": baseline_id, "manifest_sha256": sha256_bytes(raw)}


def _assert_local_only_install(workspace_root: Path) -> None:
    status = (
        workspace_root
        / "04_Manifests/Tools/LocalFirst/SafetyControls/INSTALLATION_STATUS.json"
    )
    if not status.is_file():
        raise GateError("SafetyControls installation status is missing")
    try:
        value = json.loads(status.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("SafetyControls installation status is unreadable") from exc
    forbidden = {
        "publication_wiring_enabled": value.get("publication_wiring_enabled"),
        "drive_operations_enabled": value.get("drive_operations_enabled"),
        "remote_deletion_enabled": value.get("remote_deletion_enabled"),
    }
    enabled = sorted(key for key, state in forbidden.items() if state is not False)
    if enabled:
        raise GateError("Local-only invariant failed: " + ", ".join(enabled))


def _relative_to_workspace(path: Path, workspace_root: Path) -> str:
    if not _is_within(path, workspace_root):
        raise PathSafetyError(f"Path escapes local workspace: {path}")
    relative = os.path.relpath(path, workspace_root).replace("\\", "/")
    return validate_relative_path(relative)


def _file_state(path: Path, *, relative: str) -> dict[str, Any]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or is_reparse_or_symlink(path):
        raise PathSafetyError(f"Write target is not a regular local file: {path}")
    return {
        "relative_path": relative,
        "size_bytes": info.st_size,
        "last_write_ns": info.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def _target_state(
    target: Path, *, target_kind: str, workspace_root: Path
) -> dict[str, Any]:
    relative = _relative_to_workspace(target, workspace_root)
    reject_reparse_chain(workspace_root, target, include_candidate=target.exists())
    if target_kind == "file":
        if not target.exists():
            return {"kind": "file", "relative_path": relative, "state": "ABSENT"}
        if not target.is_file():
            raise GateError(f"Expected file write target: {target}")
        return {
            "kind": "file",
            "relative_path": relative,
            "state": "PRESENT",
            "files": [_file_state(target, relative=relative)],
        }
    if target.exists() and not target.is_dir():
        raise GateError(f"Expected directory write target: {target}")
    if not target.exists():
        return {"kind": "tree", "relative_path": relative, "state": "ABSENT", "files": [], "directories": []}
    files: list[dict[str, Any]] = []
    directories: list[str] = []
    for current, dirnames, filenames in os.walk(target, topdown=True, followlinks=False):
        current_path = Path(current)
        reject_reparse_chain(workspace_root, current_path)
        for dirname in sorted(dirnames, key=str.casefold):
            directory = current_path / dirname
            if is_reparse_or_symlink(directory):
                raise PathSafetyError(f"Reparse directory in write target: {directory}")
            directories.append(_relative_to_workspace(directory, workspace_root))
        for filename in sorted(filenames, key=str.casefold):
            path = current_path / filename
            rel = _relative_to_workspace(path, workspace_root)
            files.append(_file_state(path, relative=rel))
    files.sort(key=lambda item: item["relative_path"].casefold())
    directories.sort(key=str.casefold)
    return {
        "kind": "tree",
        "relative_path": relative,
        "state": "PRESENT",
        "files": files,
        "directories": directories,
    }


def _first_party_bindings(generator_root: Path, workspace_root: Path) -> list[dict[str, Any]]:
    candidates = [generator_root / "Run-Generator.ps1"]
    engine = generator_root / "engine"
    excluded = {
        "generator_deps", "zarr_deps", "table_deps", "runtime_work",
        "bounded_real_terrain_test_2026-08-28", "__pycache__",
    }
    for path in engine.rglob("*.py"):
        if any(part in excluded for part in path.relative_to(engine).parts):
            continue
        candidates.append(path)
    for name in ("generator_source_catalogue.json", "RUNTIME_REQUIREMENTS_LOCK.txt"):
        path = generator_root / name
        if path.is_file():
            candidates.append(path)
    safety_root = workspace_root / "04_Manifests/Tools/LocalFirst/SafetyControls"
    candidates.append(safety_root / "INSTALLATION_STATUS.json")
    candidates.extend((safety_root / "package/src/diadem_safety").glob("*.py"))
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(candidates, key=lambda item: str(item).casefold()):
        relative = _relative_to_workspace(path, workspace_root)
        key = relative.casefold()
        if key in seen:
            continue
        seen.add(key)
        records.append(_file_state(path, relative=relative))
    return records


def _resolve_profile(
    *, workspace_root: Path, generator_root: Path, task: str,
    database: str | None, output_directory: str | None,
    run_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if task not in TASKS:
        raise GateError(f"Unsupported official generator task: {task}")
    if database and task not in {"ExportTables", "Population"}:
        raise GateError("Database is valid only for ExportTables or Population")
    if output_directory and task not in {"ExportTables", "Full", "Smoke", "Refine10m", "Physical10m", "Population", "TerrainReference"}:
        raise GateError("OutputDirectory is not supported by this task")
    options = _validated_run_options(task, {} if run_options is None else run_options)
    if task in {"Refine10m", "Physical10m", "Population", "TerrainReference"} and not output_directory:
        raise GateError("Later-stage runs require an explicit isolated OutputDirectory")
    if task == "Population" and not database:
        raise GateError("Population requires an explicit source Database")
    profile = dict(TASKS[task])
    entry = generator_root / profile["entry"]
    if not entry.exists():
        raise GateError(f"Official task entry is missing: {entry}")
    invocation: dict[str, Any] = {"task": task, "database": None, "output_directory": None, "run_options": options}
    if task == "TerrainReference":
        if set(options) != {"recipe_path", "recipe_sha256", "resume"}:
            raise GateError("TerrainReference requires an exact recipe binding and resume choice")
        recipe = Path(options["recipe_path"]).absolute()
        if not _is_within(recipe, workspace_root) or not recipe.is_file():
            raise GateError("Terrain recipe must be an existing file within the local workspace")
        reject_reparse_chain(workspace_root, recipe)
        if recipe.stat().st_size > 16 * 1024 * 1024 or sha256_file(recipe) != options["recipe_sha256"]:
            raise GateError("Terrain recipe is oversized or changed since launcher binding")
        if _is_within(recipe, Path(output_directory).absolute()):
            raise GateError("Terrain output must not contain its input recipe")
    if task in {"ExportTables", "Population"}:
        db = Path(database).expanduser().absolute() if database else (
            generator_root / "additional_stage6c_inputs/stage6b_parent_sqlite/Diadem_Province_Database_V3_STAGE6B_FUNCTIONAL_CLASSIFICATION_WORKING_2026-08-27.sqlite"
        )
        if not _is_within(db, workspace_root) or not db.is_file():
            raise GateError("Source database must be an existing file inside the local workspace")
        reject_reparse_chain(workspace_root, db)
        output = Path(output_directory).expanduser().absolute() if output_directory else (
            generator_root / profile["target"]
        )
        allowed = generator_root / "generated_outputs"
        if not _is_within(output, allowed) or _norm(output) == _norm(allowed):
            raise GateError("Output must be a child of 06_Generator_System/generated_outputs")
        if _is_within(db, output):
            raise GateError("Output directory must not contain the source database")
        reject_reparse_chain(generator_root, output, include_candidate=output.exists())
        target = output
        invocation["database"] = _relative_to_workspace(db, workspace_root)
        invocation["output_directory"] = _relative_to_workspace(output, workspace_root)
    elif output_directory:
        output = Path(output_directory).expanduser().absolute()
        allowed = generator_root / "generated_outputs"
        if not _is_within(output, allowed) or _norm(output) == _norm(allowed):
            raise GateError("Output must be a child of 06_Generator_System/generated_outputs")
        reject_reparse_chain(generator_root, output, include_candidate=output.exists())
        target = output
        profile["target_kind"] = "tree"
        invocation["output_directory"] = _relative_to_workspace(output, workspace_root)
    else:
        target = generator_root / profile["target"] if profile["target"] else None
    return {"profile": profile, "invocation": invocation, "target": target}


def _validated_run_options(task: str, value: dict[str, Any]) -> dict[str, Any]:
    """Bind documented typed switches; never accept arbitrary child arguments."""
    allowed = {
        "Full": {"no_reuse", "workers", "memory_budget_mb", "prefetch_workers", "prefetch_depth", "prefetch_memory_mib"},
        "Smoke": {"no_reuse", "workers", "memory_budget_mb", "smoke_limit", "prefetch_workers", "prefetch_depth", "prefetch_memory_mib"},
        "Refine10m": {"no_reuse", "workers", "memory_budget_mb", "smoke_limit"},
        "Physical10m": {"no_reuse", "workers", "memory_budget_mb", "scope"},
        "Population": {"no_reuse", "workers", "memory_budget_mb", "expected_active_sites"},
        "TerrainReference": {"recipe_path", "recipe_sha256", "resume"},
    }.get(task, set())
    if task in {"Full", "Smoke", "Refine10m", "Physical10m", "Population"}:
        allowed.add("algorithm_mode")
    if not isinstance(value, dict) or set(value) - allowed:
        raise GateError(f"Unsupported run options for {task}")
    limits = {
        "workers": (1, 32), "memory_budget_mb": (64, 65536),
        "prefetch_workers": (1, 32), "prefetch_depth": (1, 64),
        "prefetch_memory_mib": (256, 65536), "smoke_limit": (1, 31271),
        "expected_active_sites": (1, 1000000),
    }
    for key, item in value.items():
        if key in {"no_reuse", "resume"}:
            if type(item) is not bool:
                raise GateError("no_reuse must be Boolean")
        elif key == "recipe_path":
            if type(item) is not str or not item.strip():
                raise GateError("recipe_path requires a nonblank absolute path")
            if not Path(item).is_absolute():
                raise GateError("recipe_path must be absolute")
        elif key == "recipe_sha256":
            if type(item) is not str or len(item) != 64 or any(c not in "0123456789abcdef" for c in item):
                raise GateError("recipe_sha256 requires lowercase SHA256")
        elif key == "scope":
            if item not in {"FT0", "ALL"}:
                raise GateError("Physical scope must be FT0 or ALL")
        elif key == "algorithm_mode":
            if type(item) is not str or item not in {"auto", "reference"}:
                raise GateError("algorithm_mode must be auto or reference")
        elif type(item) is not int or not limits[key][0] <= item <= limits[key][1]:
            raise GateError(f"Invalid bounded run option: {key}")
    if task == "Refine10m" and value.get("smoke_limit", 1) > 107:
        raise GateError("Refine10m smoke limit exceeds 107 candidates")
    if task == "Physical10m" and value.get("memory_budget_mb", 1024) < 512:
        raise GateError("Physical10m needs at least 512 MiB for one admitted site")
    if task in {"Full", "Smoke"} and value.get("memory_budget_mb", 1024) < 256:
        raise GateError("Assessment computation needs at least 256 MiB for one admitted group")
    return dict(value)


def _read_record(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "RUN_RECORD.json"
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"Run record is unavailable or invalid: {path}") from exc
    if not isinstance(value, dict):
        raise GateError("Run record must be an object")
    return value


def _write_record(run_dir: Path, record: dict[str, Any]) -> None:
    atomic_write_json(run_dir / "RUN_RECORD.json", record, overwrite=True)


def _verify_bindings(workspace_root: Path, bindings: list[dict[str, Any]]) -> None:
    for expected in bindings:
        path = workspace_root / Path(expected["relative_path"])
        reject_reparse_chain(workspace_root, path)
        observed = _file_state(path, relative=expected["relative_path"])
        if observed != expected:
            raise GateError(f"Generator source changed after gate preparation: {expected['relative_path']}")


def _verify_snapshot(record: dict[str, Any], snapshot_root: Path) -> None:
    expected = record.get("snapshot")
    if not isinstance(expected, dict):
        raise GateError("Write-bearing task lacks snapshot evidence")
    report = RecoveryInspector().inspect(snapshot_root)
    matches = [item for item in report["complete"] if item["snapshot_id"] == expected["snapshot_id"]]
    if len(matches) != 1:
        raise GateError("Exact immutable pre-run snapshot is not verifiable")
    verified = matches[0]
    for key in ("snapshot_id", "manifest_sha256", "run_id", "baseline_id", "baseline_manifest_sha256"):
        if verified.get(key) != expected.get(key):
            raise GateError(f"Pre-run snapshot binding mismatch: {key}")


def prepare_run(
    *, workspace_root: Path, task: str, database: str | None = None,
    output_directory: str | None = None,
    run_options: dict[str, Any] | None = None,
) -> dict[str, str]:
    workspace_root = _require_regular_root(workspace_root, field="workspace_root")
    generator_root = _require_regular_root(workspace_root / GENERATOR_RELATIVE, field="generator_root")
    _assert_local_only_install(workspace_root)
    baseline = _manifest_identity(workspace_root)
    resolved = _resolve_profile(
        workspace_root=workspace_root, generator_root=generator_root, task=task,
        database=database, output_directory=output_directory,
        run_options=run_options,
    )
    bindings = _first_party_bindings(generator_root, workspace_root)
    target_state = None
    if resolved["target"] is not None:
        target_state = _target_state(
            resolved["target"], target_kind=resolved["profile"]["target_kind"],
            workspace_root=workspace_root,
        )
    invocation = resolved["invocation"]
    invocation_sha256 = sha256_bytes(canonical_json_bytes(invocation))
    run_id = "gen-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    validate_identifier(run_id, "run_id")
    gate_root = generator_root / "runtime_work/launch_gate"
    run_dir = gate_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    token = secrets.token_urlsafe(32)
    intent = {
        "schema_version": 1,
        "record_kind": "generator_launch_intent",
        "run_id": run_id,
        "task": task,
        "operation": f"official_generator_task:{task}",
        "invocation": invocation,
        "invocation_sha256": invocation_sha256,
        "expected_baseline": baseline,
        "source_bindings": bindings,
        "target_pre_state": target_state,
        "local_only": True,
        "drive_operations_enabled": False,
        "publication_enabled": False,
        "remote_deletion_enabled": False,
        "created_at_utc": _utc_now(),
    }
    atomic_write_json(run_dir / "LAUNCH_INTENT.json", intent)
    make_read_only(run_dir / "LAUNCH_INTENT.json")
    snapshot_evidence = None
    plan_sha256 = None
    if target_state is not None:
        items = [{"relative_path": MANIFEST_RELATIVE, "kind": "file", "capture": "copy", "required": True}]
        for file_record in target_state.get("files", []):
            items.append({"relative_path": file_record["relative_path"], "kind": "file", "capture": "copy", "required": True})
        plan = {
            "schema_version": 1,
            "run_id": run_id,
            "operation": intent["operation"],
            "baseline_id": baseline["baseline_id"],
            "baseline_manifest_sha256": baseline["manifest_sha256"],
            "created_by": "diadem_generator_launch_gate_v1",
            "items": items,
            "output": {"seal_tar_zst": False},
        }
        plan_path = run_dir / "SNAPSHOT_PLAN.json"
        atomic_write_json(plan_path, plan)
        plan_sha256 = sha256_file(plan_path)
        make_read_only(plan_path)
        snapshot_root = workspace_root / "05_Recovery/generator_pre_run_snapshots"
        result = PreRunSnapshotter().create(
            workspace_root=workspace_root,
            snapshot_root=snapshot_root,
            plan_path=plan_path,
            quiescence_receipt_path=run_dir / "NO_DATABASES.receipt.json",
        )
        snapshot_manifest = result["snapshot"]
        snapshot_directory = Path(result["snapshot_directory"])
        snapshot_evidence = {
            "snapshot_id": snapshot_manifest["snapshot_id"],
            "manifest_sha256": sha256_file(snapshot_directory / "MANIFEST.json"),
            "run_id": snapshot_manifest["run_id"],
            "baseline_id": snapshot_manifest["baseline_id"],
            "baseline_manifest_sha256": snapshot_manifest["baseline_manifest_sha256"],
            "plan_sha256": snapshot_manifest["plan_sha256"],
            "snapshot_directory": str(snapshot_directory),
        }
        if snapshot_evidence["plan_sha256"] != plan_sha256:
            raise GateError("Snapshot plan hash binding failed")
    record = {
        "schema_version": 1,
        "record_kind": "generator_run",
        "run_id": run_id,
        "task": task,
        "operation": intent["operation"],
        "state": "GATED",
        "invocation_sha256": invocation_sha256,
        "baseline": baseline,
        "intent_sha256": sha256_file(run_dir / "LAUNCH_INTENT.json"),
        "target_pre_state_sha256": sha256_bytes(canonical_json_bytes(target_state)),
        "plan_sha256": plan_sha256,
        "snapshot": snapshot_evidence,
        "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
        "gated_at_utc": _utc_now(),
        "started_at_utc": None,
        "completed_at_utc": None,
        "exit_code": None,
        "post_state_sha256": None,
    }
    _write_record(run_dir, record)
    return {"run_id": run_id, "token": token, "run_directory": str(run_dir)}


def _load_intent(run_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = run_dir / "LAUNCH_INTENT.json"
    if sha256_file(path) != record.get("intent_sha256"):
        raise GateError("Immutable launch intent hash mismatch")
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict) or value.get("run_id") != record.get("run_id"):
        raise GateError("Launch intent does not match run record")
    return value


def _authenticate(record: dict[str, Any], token: str) -> None:
    observed = hashlib.sha256(token.encode("ascii")).hexdigest()
    if not secrets.compare_digest(observed, str(record.get("token_sha256", ""))):
        raise GateError("Invalid launch-gate token")


def _locate_run(workspace_root: Path, run_id: str) -> tuple[Path, Path]:
    validate_identifier(run_id, "run_id")
    generator_root = workspace_root / GENERATOR_RELATIVE
    run_dir = generator_root / "runtime_work/launch_gate/runs" / run_id
    reject_reparse_chain(generator_root, run_dir)
    if not run_dir.is_dir():
        raise GateError(f"Run directory not found: {run_id}")
    return generator_root, run_dir


def authorize_run(*, workspace_root: Path, run_id: str, token: str) -> dict[str, Any]:
    workspace_root = _require_regular_root(workspace_root, field="workspace_root")
    _assert_local_only_install(workspace_root)
    _generator_root, run_dir = _locate_run(workspace_root, run_id)
    record = _read_record(run_dir)
    _authenticate(record, token)
    if record.get("state") != "GATED":
        raise GateError(f"Launch authorization is single-use; state is {record.get('state')!r}")
    intent = _load_intent(run_dir, record)
    if _manifest_identity(workspace_root) != intent["expected_baseline"]:
        raise GateError("Baseline ID or manifest hash rotated after gate preparation")
    _verify_bindings(workspace_root, intent["source_bindings"])
    expected_target = intent["target_pre_state"]
    if expected_target is not None:
        target = workspace_root / Path(expected_target["relative_path"])
        observed_target = _target_state(
            target, target_kind=expected_target["kind"], workspace_root=workspace_root
        )
        if observed_target != expected_target:
            raise GateError("Declared write target changed after recovery snapshot")
        _verify_snapshot(record, workspace_root / "05_Recovery/generator_pre_run_snapshots")
    record["state"] = "RUNNING"
    record["started_at_utc"] = _utc_now()
    _write_record(run_dir, record)
    return {"run_id": run_id, "state": "RUNNING", "task": record["task"]}


def finish_run(
    *, workspace_root: Path, run_id: str, token: str, state: str, exit_code: int,
) -> dict[str, Any]:
    workspace_root = _require_regular_root(workspace_root, field="workspace_root")
    _generator_root, run_dir = _locate_run(workspace_root, run_id)
    record = _read_record(run_dir)
    _authenticate(record, token)
    if state not in TERMINAL_STATES:
        raise GateError(f"Invalid terminal state: {state}")
    current_state = record.get("state")
    if current_state != "RUNNING" and not (current_state == "GATED" and state == "ABORTED"):
        raise GateError(
            f"Only RUNNING, or GATED as ABORTED, may be finalized; state is {current_state!r}"
        )
    intent = _load_intent(run_dir, record)
    target = intent["target_pre_state"]
    post_state = None
    if target is not None and current_state == "RUNNING":
        post_state = _target_state(
            workspace_root / Path(target["relative_path"]),
            target_kind=target["kind"], workspace_root=workspace_root,
        )
    record["state"] = state
    record["completed_at_utc"] = _utc_now()
    record["exit_code"] = int(exit_code)
    record["post_state_sha256"] = sha256_bytes(canonical_json_bytes(post_state))
    _write_record(run_dir, record)
    return {"run_id": run_id, "state": state, "exit_code": int(exit_code)}
