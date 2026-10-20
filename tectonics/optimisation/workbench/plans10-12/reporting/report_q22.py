"""Offline Plan12 descriptive report; never dispatches, imports science or grants acceptance."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys


TASK = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
PLAN12 = Path(__file__).resolve().parent
INTEGRATION = Path(__file__).resolve().parents[2] / "work/plan05/integrated-r13"
INPUT = "W4 same-call control (C/step7_same_call_heat_control.py)"
LAYOUTS = ("lw", "ld3", "le3", "lf3", "lh")
LABELS = dict(zip(LAYOUTS, ("base", "h12", "h12c", "h12cl1", "h5a"), strict=True))
SCHEDULE = [dict(mode="time", layout=name, label=LABELS[name])
            for name in (*LAYOUTS, *reversed(LAYOUTS))]
SCHEDULE.append(dict(mode="prof", layout="lh", label="h5a"))
TRANSITIONS = (("lw", "ld3", "H1a r3 + H2"), ("ld3", "le3", "H1c r3"),
               ("le3", "lf3", "L1 r4 plus physical-order repair and startup/retention cost"),
               ("lf3", "lh", "H5a; both sides carry the physical-order repair"),
               ("lw", "lh", "Whole cumulative stack on this W4 control"))
ARRAYS = {"enthalpy_j", "input_capacity_j_k", "input_enthalpy_j", "input_source_w", "temperature_k"}
METRICS = ("arm_wall_seconds", "control_wall_seconds", "legacy_s", "compact_s",
           "reconstruction_call_1_seconds", "reconstruction_call_2_seconds", "tree_peak_mib")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            result.update(block)
    return result.hexdigest()


def regular(path):
    """Refuse symlink/reparse inputs instead of following them into another tree."""
    path = Path(path).absolute()
    for component in (path, *path.parents):
        stat = component.lstat()
        require(not component.is_symlink() and not (getattr(stat, "st_file_attributes", 0) & 0x400),
                "Symlink/reparse input is outside this reporting contract: " + str(component))
    require(path.is_file(), "Expected regular input: " + str(path))
    return path


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON constant: " + value)

    return json.loads(regular(path).read_text(encoding="utf8"), object_pairs_hook=pairs,
                      parse_constant=invalid)


def number(value, name, *, positive=False, signed=False):
    require(type(value) in (int, float) and math.isfinite(value)
            and (signed or (value > 0 if positive else value >= 0)),
            "Invalid measured " + name)
    return value


def sha(value, name):
    require(isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value), "Invalid SHA256: " + name)
    return value


def same_path(value, expected, name):
    require(isinstance(value, str) and Path(value).is_absolute()
            and Path(value).resolve() == Path(expected).resolve(), name + " path differs")


def completed(value, name):
    require(value.get("passed") is True and value.get("finality") == "COMPLETE"
            and type(value.get("exit_code")) is int and value["exit_code"] == 0
            and value.get("errors") == [] and value.get("log_final") is True,
            name + " process/log completion failed")
    last = value.get("last_observation", {})
    require(last.get("job", {}).get("active") == 0 and last.get("exit_code") == 0,
            name + " owned-job finality is unresolved")
    number(value["wall_seconds"], name + " supervised wall seconds", positive=True)


def stage_record(run, name, stage):
    completed(stage, name)
    require(read_json(run / (name + ".process.json")) == stage, name + " process receipt differs")
    hashes = stage.get("log_sha256", {})
    require(set(hashes) == {"stdout", "stderr"}, name + " log bindings missing")
    for suffix in ("stdout", "stderr"):
        path = regular(run / (name + "." + suffix + ".log"))
        require(digest(path) == sha(hashes[suffix], name + " " + suffix), name + " log bytes changed")


def arm_record(run, index, summary, stage, selection_path, selection_sha):
    expected = SCHEDULE[index]
    require(type(summary.get("arm")) is int and summary["arm"] == index
            and summary.get("mode") == expected["mode"] and summary.get("label") == expected["label"],
            "Missing, extra or reordered arm " + str(index))
    layout = TASK / "hs" / expected["layout"]
    same_path(summary.get("layout"), layout, "Summary layout")
    require(summary.get("input") == INPUT and summary.get("status") == "PASS"
            and type(summary.get("exit_code")) is int and summary["exit_code"] == 0
            and type(summary.get("leaks")) is int and summary["leaks"] == 0
            and "stopped" not in summary and summary.get("used") == [6, 6]
            and all(type(value) is int for value in summary["used"])
            and summary.get("fallback") == [None, None], "Incomplete arm " + str(index))
    native = read_json(run / ("arm-" + str(index) + ".json"))
    ab = native["ab"]
    require(native.get("status") == "PASS" and ab.get("leaks") == []
            and ab.get("mode") == expected["mode"], "Native completion differs")
    same_path(ab.get("layout"), layout, "Native layout")
    for key in ("hash_randomization", "worker_probe_hash_randomization"):
        require(type(ab["interpreter"].get(key)) is int and ab["interpreter"][key] == 0,
                "Native seed proof missing: " + key)
    binding = ab["consumer_selection"]
    same_path(binding.get("path"), selection_path, "Native selection")
    require(binding.get("sha256") == selection_sha and binding.get("historical_q10") == "FAIL",
            "Native selection binding differs")
    calls = ab["calls"]
    require(isinstance(calls, list) and len(calls) == 2 and all(
        type(call.get("workers")) is int and call["workers"] == 6 and call.get("fallback") is None
        for call in calls), "Native worker route differs")
    require(type(ab.get("workers_configured")) is int and ab["workers_configured"] == 6,
            "Native configured worker count differs")
    expected_metrics = dict(legacy_s=native["legacy"]["seconds"], compact_s=native["compact"]["seconds"],
                            recon_s=[call["seconds"] for call in calls],
                            worker_cpu_s=[call["worker_compute_seconds"] for call in calls],
                            parent_cpu_seconds=ab["parent_cpu_seconds"],
                            arm_wall_seconds=stage["wall_seconds"],
                            tree_peak_mib=stage["peak_sampled_tree_rss_bytes"] / (1 << 20),
                            available_low_mib=stage["free_low_bytes"] / (1 << 20),
                            parent_peak_mib=ab["parent_peak_working_set"] / (1 << 20),
                            worker_peak_mib=max(call["worker_working_set_peak_max"] for call in calls) / (1 << 20))
    for key, value in expected_metrics.items():
        require(summary.get(key) == value, "Summary/native metric differs: " + key)
        for scalar in (value if isinstance(value, list) else [value]):
            number(scalar, key)
    require(set(native["arrays"]) == ARRAYS and summary.get("arrays") == native["arrays"],
            "Array identity coverage differs")
    for key, value in native["arrays"].items():
        sha(value, key)
    require(summary.get("result_id") == sha(native["compact"]["result_id"], "result identity"),
            "Result identity differs")
    for key in ("exact_growth_sha256", "gmp_resources_sha256"):
        require(summary.get(key) == sha(ab[key], key), "Native helper identity differs")
    require(summary.get("worker_processes") is None and isinstance(summary.get("worker_processes_basis"), str),
            "Distinct worker PID count was invented or its limitation omitted")
    own = ab["parent_cpu_seconds"] + sum(call["worker_compute_seconds"] for call in calls)
    busy = number(summary.get("machine_busy_cpu_seconds"), "machine busy CPU seconds")
    require(summary.get("accounted_cpu_seconds") == own
            and summary.get("other_load_cpus") == (busy - own) / stage["wall_seconds"]
            and isinstance(summary.get("other_load_basis"), str) and summary["other_load_basis"].strip(),
            "Qualified busy-load observation differs")
    for key in ("predicted_peak_gib", "start_gate_gib", "required_start_gate_bytes"):
        number(summary[key], key, positive=True)
    for key in ("free_gib_at_start", "gate_waited_s"):
        number(summary[key], key)
    require(summary.get("start_gate_passed") is True and isinstance(summary.get("prediction_basis"), str)
            and summary["prediction_basis"].strip() and isinstance(summary.get("prediction_history"), list)
            and len(summary["prediction_history"]) == 2, "Prediction/start observation incomplete")
    sha(summary.get("prediction_writer_sha256"), "prediction writer")
    control = number(ab["control_wall_seconds"], "native control wall seconds", positive=True)
    result = dict(index=index, mode=expected["mode"], layout=expected["layout"],
                  summary=deepcopy(summary), native_control_wall_seconds=control,
                  native_control_elapsed_seconds=native.get("elapsed_seconds"),
                  native_reconstruction_calls=deepcopy(calls),
                  metrics={key: summary[key] for key in ("arm_wall_seconds", "legacy_s", "compact_s", "tree_peak_mib")})
    result["metrics"].update(control_wall_seconds=control,
                              reconstruction_call_1_seconds=summary["recon_s"][0],
                              reconstruction_call_2_seconds=summary["recon_s"][1])
    if expected["mode"] == "prof":
        profiles = summary.get("profile_files")
        require(isinstance(profiles, list) and profiles, "Profile artefacts missing")
        seen = set()
        for profile in profiles:
            relative = Path(profile["path"])
            require(not relative.is_absolute() and relative.parent == Path("arm-10")
                    and relative.name.startswith("worker-") and relative.suffix == ".prof"
                    and str(relative) not in seen, "Profile route or uniqueness differs")
            seen.add(str(relative))
            path = regular(run / relative)
            require(type(profile["bytes"]) is int and profile["bytes"] > 0
                    and path.stat().st_size == profile["bytes"]
                    and digest(path) == sha(profile["sha256"], "profile"), "Profile bytes differ")
        actual = {str(path.relative_to(run)) for path in (run / "arm-10").glob("worker-*.prof")}
        require(seen == actual, "Unreported profile artefacts")
    return result


def disk_inventory(run):
    files = []
    pending = [run]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                stat = entry.stat(follow_symlinks=False)
                require(not entry.is_symlink() and not (getattr(stat, "st_file_attributes", 0) & 0x400),
                        "Run contains a symlink/reparse entry")
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                else:
                    require(entry.is_file(follow_symlinks=False), "Run contains a non-regular entry")
                    files.append(dict(path=str(path.relative_to(run)), bytes=stat.st_size))
    files.sort(key=lambda item: item["path"])
    return dict(status="MEASURED_RETAINED_LOGICAL_BYTES", file_count=len(files),
                bytes=sum(item["bytes"] for item in files), files=files,
                basis="Current regular-file lengths inside the selected run output, including source snapshots, logs and profiles.",
                compressed_or_allocated_disk_bytes=None, transient_peak_disk_bytes=None,
                limitation="Logical file lengths do not measure filesystem compression, allocated clusters or deleted/transient peak use.")


def comparison(old, new):
    left = [item["metrics"] for item in old]
    right = [item["metrics"] for item in new]
    result = {}
    for key in METRICS:
        old_values, new_values = [item[key] for item in left], [item[key] for item in right]
        old_mean, new_mean = math.fsum(old_values) / 2, math.fsum(new_values) / 2
        result[key] = dict(old_observations=old_values, new_observations=new_values,
                           old_mean=old_mean, new_mean=new_mean, reduction=old_mean - new_mean,
                           percent_reduction=100 * (old_mean - new_mean) / old_mean if old_mean else None,
                           percent_basis="100 * (old descriptive mean - new descriptive mean) / old descriptive mean; null if old mean is zero")
    return result


def queue_metrics(path, run, timing_wall, profile_wall, checker_wall, gate_wait):
    unavailable = dict(status="UNAVAILABLE", admitted_payload_elapsed_seconds=None,
                       admitted_payload_residual_seconds=None, pre_admission_queue_wait_seconds=None,
                       isolated_queue_overhead_seconds=None,
                       basis="No supplied completed q22 record; per-arm gate waits are reported separately.")
    if path is None:
        return unavailable
    value = read_json(path)
    if "tickets" in value:
        matches = [item for item in value["tickets"] if item.get("id") == "q22"]
        require(len(matches) == 1, "Queue document must contain exactly one q22 record")
        value = matches[0]
    require(value.get("id") == "q22" and value.get("status") == "done"
            and type(value.get("exit")) is int and value["exit"] == 0,
            "Supplied q22 record is not a completed successful record")
    outputs = value.get("outputs")
    if isinstance(outputs, str):
        outputs = [outputs]
    require(isinstance(outputs, list) and any(isinstance(item, str) and Path(item).is_absolute()
            and Path(item).resolve() == run for item in outputs), "q22 queue output does not bind this run")
    result = dict(unavailable, source=dict(path=str(Path(path).resolve()), sha256=digest(path)), record=deepcopy(value))
    if not all(isinstance(value.get(key), str) for key in ("started", "ended")):
        result["basis"] = "The supplied matching q22 record has no complete started/ended pair."
        return result
    start, end = (datetime.fromisoformat(value[key]) for key in ("started", "ended"))
    require(start.utcoffset() is not None and end.utcoffset() is not None, "q22 timestamps need explicit offsets")
    elapsed = (end - start).total_seconds()
    number(elapsed, "q22 admitted payload elapsed seconds")
    residual = elapsed - math.fsum((timing_wall, profile_wall, checker_wall, gate_wait))
    result.update(status="MEASURED_COARSE_ADMITTED_PAYLOAD_ELAPSED", admitted_payload_elapsed_seconds=elapsed,
                  admitted_payload_residual_seconds=residual,
                  basis="runq started/ended bracket admitted command execution at whole-second precision. Residual subtracts all 11 supervised arm intervals, checker supervision and per-arm gate waits; includes wrapper/setup/source checks/logging/process-start gaps and timing-boundary differences. It is not isolated queue overhead; a small negative residual is retained.")
    return result


def current_launch_status(selection):
    """Expose decision-reference availability without granting live launch clearance."""
    references = {key: deepcopy(selection.get(key)) for key in ("correctness_acceptance", "run_authority")}
    flags = {}
    for key, value in references.items():
        present = (isinstance(value, dict) and isinstance(value.get("path"), str)
                   and Path(value["path"]).is_absolute() and isinstance(value.get("sha256"), str)
                   and len(value["sha256"]) == 64
                   and all(character in "0123456789abcdef" for character in value["sha256"]))
        flags[key + "_reference_supplied"] = present
    return dict(status="NOT_EVALUATED" if all(flags.values()) else "NON_EXECUTABLE_MISSING_DECISIONS",
                current_launch_admission_established=False, references=references, flags=flags,
                decision_contents_evaluated=False, live_source_pins_rescanned=False,
                live_queue_pin_evaluated=False,
                basis="References are shown as supplied, not verified decisions. This historical descriptive report grants no current execution authority. Live queue custody, holds, source-pin drift and the complete consumer admission gate remain unevaluated.")


def execution_route(selection):
    """Bind the optional additive route by selected paths/pins, without live rehash."""
    if "execution_route" not in selection:
        return dict(mode="HISTORICAL_INTEGRATED_ROUTE", writer=str(INTEGRATION / "ab_heat_r13.py"),
                    references=None, live_route_sources_rehashed=False)
    references = selection["execution_route"]
    filenames = dict(launcher="launch_q22.py", writer="child_q22.py",
                     adapter="launch_adapter.py", gate="migration_gate.py")
    require(isinstance(references, dict) and set(references) == set(filenames),
            "Migrated execution route reference coverage differs")
    pins = selection.get("source_pins", {})
    for key, filename in filenames.items():
        reference = references[key]
        require(isinstance(reference, dict) and set(reference) == {"path", "sha256"},
                "Malformed migrated execution route reference: " + key)
        expected = (PLAN12 / filename).resolve()
        same_path(reference["path"], expected, "Migrated " + key)
        require(pins.get(str(expected)) == sha(reference["sha256"], "migrated " + key),
                "Migrated execution route source pin differs: " + key)
    return dict(mode="MIGRATED_ADDITIVE_ROUTE", writer=str((PLAN12 / filenames["writer"]).resolve()),
                references=deepcopy(references), live_route_sources_rehashed=False)


def build_report(run, selection_path, selection_sha, queue_record=None):
    run, selection_path = Path(run).resolve(), Path(selection_path).resolve()
    require(run.is_dir(), "Selected completed run directory is missing")
    require(digest(regular(selection_path)) == sha(selection_sha, "selected manifest"), "Selected manifest bytes differ")
    selection = read_json(selection_path)
    require(selection.get("schema") == "plan12.successor-consumer-selection.r1"
            and selection.get("queue_ticket") == "q22" and selection.get("historical_q10") == "FAIL"
            and selection.get("schedule") == SCHEDULE, "Selected consumer identity/schedule differs")
    route = execution_route(selection)
    same_path(selection.get("output"), run, "Selected output")
    attempt = read_json(run / "attempt.json")
    require(attempt.get("mode") == "consumer" and attempt.get("manifest_sha256") == selection_sha
            and attempt.get("queue_ticket") == "q22", "Attempt selection binding differs")
    summary, result = read_json(run / "summary.json"), read_json(run / "result.json")
    require(result.get("schema") == "plan12-consumer-route-result.r1" and result.get("passed") is True
            and result.get("errors") == [] and result.get("historical_q10") == "FAIL",
            "Consumer route did not complete")
    arms, stages = summary.get("arms"), result.get("stages")
    require(isinstance(arms, list) and len(arms) == 11 and result.get("arms") == arms
            and isinstance(stages, list) and len(stages) == 12, "Incomplete or extra arm/stage coverage")
    native_names = {path.name for path in run.glob("arm-*.json") if path.name[4:-5].isdigit()}
    require(native_names == {"arm-" + str(index) + ".json" for index in range(11)},
            "Missing or extra native arm JSON records")
    observations = []
    for index, (arm, stage) in enumerate(zip(arms, stages[:11], strict=True)):
        stage_record(run, "arm-" + str(index), stage)
        argv = stage.get("argv", [])
        require(len(argv) == 13 and argv[1:4] == ["-B", "-s", "-P"]
                and argv[5:7] == ["child", SCHEDULE[index]["mode"]] and argv[9] == str(index)
                and argv[-3] == "--consumer-selection" and argv[-1] == selection_sha,
                "Child command selection binding differs")
        same_path(argv[0], TASK / ".r44-env/Scripts/python.exe", "Child interpreter")
        same_path(argv[4], route["writer"], "Child writer")
        same_path(argv[7], TASK / "hs" / SCHEDULE[index]["layout"], "Child command layout")
        same_path(argv[8], run, "Child command output")
        same_path(argv[-2], selection_path, "Child command selection")
        require(arm.get("prediction_history") == selection.get("prediction_history")
                and arm.get("prediction_writer_sha256") == selection.get("source_pins", {}).get(
                    str((INTEGRATION / "ab_heat_r13.py").resolve())), "Prediction selection binding differs")
        observations.append(arm_record(run, index, arm, stage, selection_path, selection_sha))
    checker = stages[-1]
    stage_record(run, "check-arms", checker)
    argv = checker.get("argv", [])
    require(len(argv) == 7 and argv[1:4] == ["-B", "-s", "-P"] and argv[-1] == "11",
            "Checker command differs")
    same_path(argv[0], TASK / ".r44-env/Scripts/python.exe", "Checker interpreter")
    same_path(argv[4], TASK / "hs/scripts/check_arms.py", "Checker source")
    same_path(argv[-2], run, "Checker output")
    check_text = regular(run / "check-arms.txt").read_bytes()
    require(check_text == regular(run / "check-arms.stdout.log").read_bytes(), "Saved checker output differs")
    lines = check_text.decode("utf8").splitlines()
    require(len(lines) == 12 and lines[-1] == "ARMS PASS" and all(
        lines[index].startswith(str(index) + " " + spec["mode"] + " " + spec["label"] + " OK ")
        for index, spec in enumerate(SCHEDULE)), "Checker did not confirm every authentic arm")
    timing, profile = observations[:10], observations[10]
    grouped = {name: [item for item in timing if item["layout"] == name] for name in LAYOUTS}
    require(all(len(items) == 2 for items in grouped.values()), "Two timing observations per layout required")
    layout_pairs = {}
    for name, items in grouped.items():
        layout_pairs[name] = dict(arm_indices=[item["index"] for item in items],
                                 observations=[deepcopy(item["metrics"]) for item in items],
                                 descriptive_means={key: math.fsum(item["metrics"][key] for item in items) / 2
                                                    for key in METRICS},
                                 second_minus_first={key: items[1]["metrics"][key] - items[0]["metrics"][key]
                                                     for key in METRICS})
    timing_wall = math.fsum(item["metrics"]["arm_wall_seconds"] for item in timing)
    profile_wall = profile["metrics"]["arm_wall_seconds"]
    checker_wall = checker["wall_seconds"]
    gate_wait = math.fsum(arm["gate_waited_s"] for arm in arms)
    return dict(schema="plan12.offline-descriptive-report.r1", status="COMPLETED_CONSUMER_DESCRIPTIVE_EVIDENCE_ONLY",
                run=str(run), selection=dict(path=str(selection_path), sha256=selection_sha),
                execution_route=route,
                current_launch_admission=current_launch_status(selection),
                input_evidence={name: dict(path=str(run / name), sha256=digest(run / name))
                                for name in ("attempt.json", "summary.json", "result.json", "check-arms.txt")},
                observations=observations, layout_pairs=layout_pairs,
                comparisons=[dict(old_layout=old, new_layout=new, attribution=attribution,
                                  metrics=comparison(grouped[old], grouped[new]))
                             for old, new, attribution in TRANSITIONS],
                profile=deepcopy(profile),
                time_accounting=dict(ten_uninstrumented_supervised_arms_seconds=timing_wall,
                                     separate_profile_supervised_arm_seconds=profile_wall,
                                     checker_supervised_seconds=checker_wall, per_arm_memory_gate_wait_seconds=gate_wait,
                                     isolated_profiling_overhead_seconds=None,
                                     profiling_basis="One separately instrumented lh observation; its difference from the timing pair is confounded by host/order differences and is not an isolated instrumentation-overhead estimate."),
                queue=queue_metrics(queue_record, run, timing_wall, profile_wall, checker_wall, gate_wait),
                disk=disk_inventory(run),
                limitations=["Two observations per layout support descriptive comparisons, not a confidence interval or a fixed speedup/noise threshold. Negative and tiny reductions are retained; no automatic enable decision or retry follows.",
                             "Mirrored second-minus-first values expose order sensitivity; mirroring cannot cancel arbitrary host load.",
                             "arm_wall_seconds is the owned-job supervision interval after process start, including sampling granularity; control_wall_seconds is the native control boundary, rounded in the retained receipt to milliseconds. Neither is a full interval measurement.",
                             "legacy_s and compact_s are separate packaging/advance timings on the same issued call; reconstruction calls are retained separately and overlap those component timings. Do not add these measures together.",
                             "tree_peak_mib samples controller plus owned-job RSS at nominal 0.25-second intervals. Native caller and largest worker OS high-water marks have a different scope and need not occur simultaneously.",
                             "other_load_cpus is observed machine busy delta minus accounted native parent/worker CPU, divided by supervision wall. It includes unaccounted process/OS work and window differences; preserve negative residuals rather than claiming isolated external load.",
                             "used=[6,6] records workers per heat call. Distinct worker PID count remains unavailable; two calls do not establish twelve distinct processes.",
                             "This offline report verifies completion and retained bindings only. It does not re-adjudicate scientific correctness, create acceptance/run authority, release a hold or change the improvements table."],
                whole_interval=dict(status="CONDITIONAL_UNMEASURED", measured_percent_reduction=None,
                                    implication="Only the selected W4 component/composition chain is measured. A whole-interval projection would need a comparable measured fraction of interval time affected and unchanged unaffected work: total ratio = (1 - f) + f * component_ratio. No f is supplied, no prediction is issued, and overlapping gains must not be added."))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--queue-record", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_report(args.run, args.selection, args.selection_sha256, args.queue_record)
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as error:
        print(json.dumps(dict(status="REFUSED", error=type(error).__name__ + ": " + str(error))), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
