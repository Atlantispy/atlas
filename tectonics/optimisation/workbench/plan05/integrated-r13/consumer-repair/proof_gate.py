"""Read-only Plan12 successor gate. It never accepts science or releases q22."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parent
TASK = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
ARRAYS = ("enthalpy_j", "input_capacity_j_k", "input_enthalpy_j",
          "input_source_w", "temperature_k")
ACCOUNTS = ("exact_cell_storage_residual_j", "exact_corrected_enthalpy_j",
            "exact_retained_solver_residual_j", "exact_stock_projection_residual_j")
SCALARS = ("exact_outward_boundary_energy_j", "exact_source_energy_j",
           "independently_supplied_absolute_residual_target")
SCHEDULE = tuple(dict(mode="time", layout=layout, label=label) for layout, label in (
    ("lw", "base"), ("ld3", "h12"), ("le3", "h12c"), ("lf3", "h12cl1"), ("lh", "h5a"),
    ("lh", "h5a"), ("lf3", "h12cl1"), ("le3", "h12c"), ("ld3", "h12"), ("lw", "base"),
)) + (dict(mode="prof", layout="lh", label="h5a"),)


class Refuse(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Refuse(reason)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise Refuse("Nonfinite JSON value: " + value)

    return json.loads(Path(path).read_text(encoding="utf8"),
                      object_pairs_hook=pairs, parse_constant=invalid)


def absolute(value):
    require(isinstance(value, str) and Path(value).is_absolute(), "Absolute path required")
    return Path(value).resolve()


def bound(record):
    require(isinstance(record, dict) and set(record) == {"path", "sha256"},
            "Exact path/hash evidence reference required")
    path = absolute(record["path"])
    require(digest(path) == record["sha256"], "Bound file changed: " + str(path))
    return path


def check_pins(pins):
    require(isinstance(pins, dict) and bool(pins), "Nonempty source/evidence pins required")
    seen = set()
    for name, expected in pins.items():
        path = absolute(name)
        require(path not in seen, "Aliased source/evidence path")
        seen.add(path)
        require(digest(path) == expected, "Pinned bytes changed: " + name)
    return seen


def required_source_paths():
    """Only named selected roots; no original-task-root traversal."""
    paths = {INTEGRATION / "ab_heat_r13.py", INTEGRATION / "launch_plan05_r13.py",
             INTEGRATION / "verify_d02_r13.py", HERE / "proof_gate.py",
             HERE / "launch_adapter.py", HERE / "worker_runtime.py", HERE / "metrics.py",
             TASK / ".r44-env/Scripts/python.exe", TASK / "q/runq.py",
             TASK / "hs/scripts/check_arms.py", TASK / "hs/workerprof/sitecustomize.py",
             INTEGRATION.parent / "r9-launch-prep/owned_windows_job.py"}
    paths.update(prediction_history_paths())
    for layout in ("lw", "ld3", "le3", "lf3", "lh"):
        control = TASK / "hs" / layout / "control.json"
        paths.add(control)
        permitted = (TASK / "hs" / layout, TASK /
                     "fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests")
        for name in read_json(control)["paths"]:
            root = absolute(name)
            require(any(root.is_relative_to(parent.resolve()) for parent in permitted),
                    "Unexpected consumer import root")
            paths.update(root.rglob("*.py"))
    return {path.resolve() for path in paths}


def prediction_history_paths():
    return tuple((TASK / "hs/evidence" / name / "summary.json").resolve()
                 for name in ("h12-r1", "h1c-r4a"))


def check_prediction_history(manifest, source_paths):
    """History is a bound input, never permission to reinterpret proof as timing."""
    metrics = (INTEGRATION / "consumer-repair/metrics.py").resolve()
    require(metrics in source_paths, "Consumer metrics source unbound")
    references = manifest.get("prediction_history")
    require(isinstance(references, list) and len(references) == 2,
            "Exactly both r2 prediction history inputs required")
    for reference, expected in zip(references, prediction_history_paths(), strict=True):
        require(isinstance(reference, dict) and set(reference) == {"path", "sha256"},
                "Exact prediction history path/hash reference required")
        path = absolute(reference["path"])
        require(path == expected, "Prediction history route or order differs")
        # check_pins has just verified these exact file bytes. Requiring the
        # same reference hash connects the history field to that checked set.
        require(path in source_paths
                and manifest["source_pins"].get(str(path)) == reference["sha256"],
                "Prediction history reference is not source-bound")


def required_proof_paths(root):
    paths = {root / name for name in ("verification.json", "attempt.json", "result.json", "summary.json")}
    for index in (0, 1):
        arm = root / ("arm-" + str(index))
        require(arm.is_dir(), "Both complete proof arm directories required")
        paths.update(path for path in arm.iterdir() if path.is_file())
        required = {"arrays.json", "legacy_metadata.json", "thermal_mesh_record.json",
                    "d02_correspondence_capture.json", "observer_disposition.json"}
        required.update(name + ".npy" for name in ARRAYS)
        require(required <= {path.name for path in arm.iterdir() if path.is_file()},
                "Proof arm companion missing")
        paths.add(root / ("arm-" + str(index) + ".json"))
    for stage in ("arm-0", "arm-1", "check-arms", "verification"):
        paths.update(root / (stage + suffix) for suffix in
                     (".process.json", ".stdout.log", ".stderr.log"))
    return {path.resolve() for path in paths}


def _bijection(values, name):
    require(isinstance(values, list) and values
            and all(type(value) is int for value in values)
            and sorted(values) == list(range(len(values))), "Incomplete " + name + " bijection")


def required_dispositions(report):
    required = {}
    for family in ("provenance_differences", "resource_differences", "header_provenance_differences"):
        for entry in report["metadata"][family]:
            key = family + ":" + entry["path"]
            require(key not in required, "Duplicate metadata disposition key")
            required[key] = canonical_hash(entry)
    return required


def check_comparison(report):
    require(report["schema"] == "atlas.private.d02-verifier.r13"
            and report["historical_q10"] == "FAIL" and report["q22"] == "HELD"
            and report["scientific_acceptance"] is False, "Verifier boundary differs")
    require(report["new_run_verdict"] in ("EXACT_COMPARISON_COMPLETE", "METADATA_DISPOSITION_REQUIRED"),
            "Repaired pair has not passed exact comparison")
    require(report["historical_q10_binding_status"] in
            ("NOT_REPRODUCED", "AGREES_WITH_PRESERVED_Q10"), "Historical comparison missing")
    require(report["corresponding_inputs_equal"] is True
            and report["solver_attribution_permitted"] is True
            and report["physical_context_mismatches"] == [], "Physical/input proof incomplete")
    _bijection(report["cell_bijection_pi"], "cell")
    _bijection(report["face_bijection_sigma"], "face")
    require(len(report["face_orientation"]) == len(report["face_bijection_sigma"])
            and all(type(sign) is int and sign in (-1, 1) for sign in report["face_orientation"]),
            "Incomplete signed face mapping")
    for name, fields, boolean, differences in (
        ("arrays", ARRAYS, "bitwise_equal", "differing_rows"),
        ("exact_cell_accounts", ACCOUNTS, "exact_equal", "differing_rows"),
    ):
        require(set(report[name]) == set(fields), "Missing/extra " + name)
        require(all(report[name][key][boolean] is True and report[name][key][differences] == []
                    for key in fields), "Unequal " + name)
    require(report["exact_face_account"]["exact_equal"] is True
            and report["exact_face_account"]["differing_faces"] == [], "Unequal paired-face accounts")
    require(set(report["exact_scalars"]) == set(SCALARS)
            and all(value is True for value in report["exact_scalars"].values()), "Unequal scalars")
    require(report["within_arm_ledger_errors"] == {"arm_a": [], "arm_b": []}, "Within-arm ledger failure")
    metadata = report["metadata"]
    require(metadata["coverage"] == "ALL_LEAVES"
            and metadata["invariant_differences"] == [] and metadata["proof_failures"] == []
            and metadata["unresolved_required_evidence"] == [], "Metadata proof incomplete")
    require(len(metadata["leaf_dispositions"]) == metadata["compared_leaves"]
            + metadata["separately_mapped_account_and_axis_leaves"], "Metadata coverage count differs")
    return required_dispositions(report)


def _proof_finality(root, selection_sha):
    attempt = read_json(root / "attempt.json")
    require(attempt == {"mode": "capture", "manifest_sha256": selection_sha}, "Proof launch binding differs")
    result = read_json(root / "result.json")
    require(result["schema"] == "plan05-route-result.v1" and result["mode"] == "capture"
            and result["historical_q10"] == "FAIL" and result["q22"] == "HELD",
            "Proof route receipt differs")
    require(len(result["stages"]) == 4, "Incomplete proof route")
    for name, stage in zip(("arm-0", "arm-1", "check-arms", "verification"), result["stages"], strict=True):
        require(stage == read_json(root / (name + ".process.json")), "Stage receipt differs")
        require(stage["finality"] == "COMPLETE" and stage["log_final"] is True
                and stage["last_observation"]["job"]["active"] == 0 and stage["errors"] == [],
                "Proof process/log finality incomplete")
        expected_exits = (0, 1) if name == "verification" else (0,)
        require(type(stage["exit_code"]) is int and stage["exit_code"] in expected_exits,
                "Proof stage failed")
        if name != "verification":
            require(stage["passed"] is True, "Native proof/checker did not pass")
        for stream in ("stdout", "stderr"):
            require(digest(root / (name + "." + stream + ".log")) == stage["log_sha256"][stream],
                    "Final proof log changed")
    arms = read_json(root / "summary.json")["arms"]
    require(len(arms) == 2, "Proof arm count differs")
    for index, arm in enumerate(arms):
        require(arm["arm"] == index and arm["label"] == ("lf3", "lh")[index]
                and arm["status"] == "PASS" and arm["exit_code"] == 0 and arm["leaks"] == 0
                and arm["used"] == [6, 6] and arm["fallback"] == [None, None]
                and "stopped" not in arm, "Incomplete native proof arm")


def validate_selection(manifest_path, expected_sha):
    manifest_path = absolute(str(manifest_path))
    require(digest(manifest_path) == expected_sha, "Consumer manifest digest differs")
    manifest = read_json(manifest_path)
    require(manifest["schema"] == "plan12.successor-consumer-selection.r1"
            and manifest["historical_q10"] == "FAIL" and manifest["queue_ticket"] == "q22",
            "Consumer selection scope differs")
    require(manifest["schedule"] == list(SCHEDULE), "Authentic 11-arm schedule differs")
    source_paths = check_pins(manifest["source_pins"])
    require(required_source_paths() <= source_paths, "Required consumer source unbound")
    check_prediction_history(manifest, source_paths)
    selection_path = bound(manifest["order_selection"])
    selection = read_json(selection_path)
    require(selection["schema"] == "plan05-integrated-r13.v1" and selection["scope"] == ["lf3", "lh"]
            and selection["historical_q10"] == "FAIL" and selection["q22"] == "HELD",
            "Repaired proof selection differs")
    require(all(manifest["source_pins"].get(name) == pin
                for name, pin in selection["source_pins"].items()),
            "Consumer source selection differs from its proved source selection")
    repair = selection["order_repair"]
    require(repair["schema"] == "plan05.physical-order-selection.r1"
            and repair["scope"] == ["lf3", "lh"], "Selected order repair missing")
    expected_overlay = {INTEGRATION / "order-repair/private_heat_physical_order_r1.py"}
    expected_overlay.update(INTEGRATION / "order-repair" / arm / name for arm in ("lf3", "lh")
                            for name in ("private_heat_forward_kernel_r13.py", "private_heat_native_issuer_r13.py"))
    require({absolute(name) for name in repair["source_pins"]} ==
            {path.resolve() for path in expected_overlay}, "Repair source inventory differs")
    for name, pin in repair["source_pins"].items():
        require(selection["source_pins"].get(name) == pin and manifest["source_pins"].get(name) == pin,
                "Consumer does not select the proved repair")
    verification_path = bound(manifest["verification"])
    root = verification_path.parent
    require(verification_path.name == "verification.json", "Named proof report required")
    evidence_paths = check_pins(manifest["proof_artifacts"])
    require(evidence_paths == required_proof_paths(root), "Proof evidence set incomplete or extraneous")
    report = read_json(verification_path)
    required = check_comparison(report)
    for arm, layout in (("arm_a", "lf3"), ("arm_b", "lh")):
        evidence = report["metadata"]["evidence"]["order_repair"][arm]
        descriptor = evidence["descriptor"]
        require(evidence["status"] == "EXACT_SELECTED_REPAIR_SOURCES_BOUND"
                and evidence["launch_manifest_sha256"] == manifest["order_selection"]["sha256"]
                and descriptor["layout"] == layout
                and descriptor["manifest_sha256"] == manifest["order_selection"]["sha256"]
                and absolute(descriptor["manifest_path"]) == selection_path,
                "Report is not from the selected repaired pair")
        require(descriptor["numerical_tolerances_changed"] is False
                and descriptor["original_metric_mutated"] is False,
                "Proof changed numerical tolerance or original metric")
    _proof_finality(root, manifest["order_selection"]["sha256"])
    dispositions = read_json(bound(manifest["dispositions"]))
    require(dispositions["schema"] == "plan05.metadata-dispositions.r1"
            and dispositions["verification_sha256"] == manifest["verification"]["sha256"],
            "Metadata disposition report binding differs")
    require(set(dispositions["decisions"]) == set(required), "Metadata decisions incomplete or extraneous")
    for key, item in dispositions["decisions"].items():
        require(item["entry_sha256"] == required[key] and item["decision"] == "DISPOSITION_RECORDED"
                and isinstance(item["reason"], str) and item["reason"].strip(),
                "Metadata decision missing its exact evidence or reason")
    acceptance = read_json(bound(manifest.get("correctness_acceptance")))
    require(acceptance["schema"] == "plan05.scientific-correctness-acceptance.r1"
            and acceptance["decision"] == "ACCEPTED" and acceptance["scope"] == ["lf3", "lh"]
            and acceptance["historical_q10"] == "FAIL"
            and acceptance["historical_linkage"] == report["historical_q10_binding_status"],
            "Explicit successor correctness acceptance required")
    for name in ("order_selection", "verification", "dispositions"):
        require(acceptance[name + "_sha256"] == manifest[name]["sha256"], "Acceptance binds different evidence")
    require(acceptance["proof_artifacts_sha256"] == canonical_hash(manifest["proof_artifacts"]),
            "Acceptance binds different proof artefacts")
    bound(acceptance["authority_evidence"])
    authority = read_json(bound(manifest.get("run_authority")))
    require(authority["schema"] == "plan12.run-authority.r1"
            and authority["decision"] == "AUTHORIZED" and authority["queue_ticket"] == "q22",
            "Separate explicit q22 run authority required")
    for name in ("order_selection", "correctness_acceptance"):
        require(authority[name + "_sha256"] == manifest[name]["sha256"], "Run authority binds different decision")
    require(authority["source_pins_sha256"] == canonical_hash(manifest["source_pins"])
            and authority["schedule"] == list(SCHEDULE)
            and absolute(authority["output"]) == absolute(manifest["output"]), "Run authority route differs")
    bound(authority["authority_evidence"])
    return manifest


def validate_child(manifest_path, sha, mode, layout, out, index):
    selection = validate_selection(manifest_path, sha)
    require(type(index) is int and 0 <= index < len(SCHEDULE), "Consumer arm index outside schedule")
    expected = SCHEDULE[index]
    require(mode == expected["mode"]
            and Path(layout).resolve() == (TASK / "hs" / expected["layout"]).resolve()
            and Path(out).resolve() == absolute(selection["output"]), "Child differs from selected schedule/output")
    return selection
