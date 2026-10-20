"""Selected Plan05 route: bounded tests or one explicitly authorised D02 attempt."""
import argparse
import ctypes
from ctypes import wintypes
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

import psutil

HERE = Path(__file__).resolve().parent
W = HERE.parents[2]
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
P = T / ".r44-env/Scripts/python.exe"
PREVIOUS = HERE.parent / "r9-launch-prep"
GIB = 1 << 30
RSS_GUARD = 12 * GIB
FREE_FLOOR = GIB
BASELINE_GIB = 1.03
BACKEND_SHA = "132d53b54729c13193293ffa9b3eddd6c248f2c00e8f76aaa553f39a5f8146aa"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("Non-finite JSON: " + value)
    return json.loads(Path(path).read_text(encoding="utf8"), object_pairs_hook=pairs,
                      parse_constant=invalid)


def write_new(path, record):
    with Path(path).open("x", encoding="utf8", newline="\n") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def retain_selected_sources(manifest, out):
    """Retain mutable route/queue sources, including a failed attempt's bytes.

    The much larger frozen native layouts remain in place under their existing
    source pins; this snapshot adds no new native source or execution route.
    """
    destination = out / "source-inputs"
    destination.mkdir()
    sources = {path.resolve() for path in HERE.glob("*.py")}
    sources.update(HERE / "worker-flags-repair" / name for name in
                   ("worker_flags_repair.py", "test_worker_flags_repair.py"))
    if "order_repair" in manifest or "order_selection" in manifest:
        sources.update(Path(name) for name in manifest["source_pins"]
                       if Path(name).is_relative_to(HERE / "order-repair"))
    sources.update(Path(name) for name in manifest["source_pins"]
                   if Path(name).is_relative_to(HERE / "consumer-repair"))
    sources.update(Path(item["path"]) for item in manifest.get("prediction_history", []))
    sources.update((T / "q/runq.py", T / "hs/scripts/check_arms.py",
                    PREVIOUS / "owned_windows_job.py"))
    index = {}
    for number, path in enumerate(sorted(sources)):
        raw = path.read_bytes()
        expected = manifest["source_pins"][str(path)]
        require(hashlib.sha256(raw).hexdigest() == expected, "Source changed before retention")
        name = str(number).zfill(3) + "-" + path.name
        with (destination / name).open("xb") as stream:
            stream.write(raw)
        index[str(path)] = dict(file=name, sha256=expected)
    write_new(destination / "index.json", index)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def required_sources():
    # Exact local route plus native import roots from the two pinned layouts.
    # No original-task-root traversal and no access to T/bridge.
    sources = set(HERE.glob("*.py"))
    sources.update(HERE / "worker-flags-repair" / name for name in
                   ("worker_flags_repair.py", "test_worker_flags_repair.py"))
    # Only the additive repair's explicit code subtree, never a native-root copy.
    repair_root = HERE / "order-repair"
    if repair_root.exists():
        sources.update(repair_root.glob("*.py"))
        for layout in ("lf3", "lh"):
            sources.update((repair_root / layout).glob("*.py"))
    sources.update((HERE / "consumer-repair").glob("*.py"))
    # The real native caller also binds these three shared science helpers.
    # Exact files only: no additional import root or recursive source scan.
    shared = T / "fidelity-integration-20261005/heat-repair-20261007/source/tectonics/src/atlas_tectonics"
    sources.update(shared / name for name in
                   ("integration_exact_gmp.py", "integration_mimetic_newton.py",
                    "integration_spatial_transport.py"))
    sources.update(HERE / name for name in (
        "launch_plan05_r13.py", "run_tests_r13.py", "ab_heat_r13.py", "verify_d02_r13.py",
        "test_ownership_r13.py", "test_verifier_r13.py", "test_writer_verifier_r13.py",
        "test_launcher_r13.py"))
    sources.update((P, T / "q/runq.py", T / "hs/scripts/check_arms.py",
                    PREVIOUS / "owned_windows_job.py"))
    control = (T / "fidelity-integration-20261005/continuation-repair-20261013"
               "/optimisation-20261014/resumability-r1/compact-geometry-r1"
               "/step7_same_call_heat_control.py")
    sources.add(control)
    sources.add(control.parent.parent / "composed-checks/w4_owner_heat_child.py")
    for index in (3, 4):
        historical = T / "hs/evidence/h1c-r4a" / ("arm-" + str(index))
        sources.update(historical / name for name in (
            "arrays.json", "legacy_metadata.json", "enthalpy_j.npy",
            "input_capacity_j_k.npy", "input_enthalpy_j.npy", "input_source_w.npy",
            "temperature_k.npy"))
        sources.add(historical.with_suffix(".json"))
    for layout in ("lf3", "lh"):
        config = T / "hs" / layout / "control.json"
        sources.add(config)
        for directory in read_json(config)["paths"]:
            root = Path(directory).resolve()
            permitted = (T / "hs" / layout,
                         T / "fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests")
            require(any(root.is_relative_to(parent) for parent in permitted), "Unexpected native import root")
            sources.update(root.rglob("*.py"))
    for relative in ("lib/_npyio_impl.py", "lib/_format_impl.py"):
        sources.add(T / ".r44-env/Lib/site-packages/numpy" / relative)
    return {str(path.resolve()) for path in sources}


def require_pin_coverage(manifest, required):
    pins = manifest["source_pins"]
    missing = required - set(pins)
    require(not missing, "Unbound selected source(s): " + repr(sorted(missing)))


def verify_manifest(path, expected):
    require(digest(path) == expected, "Manifest digest mismatch")
    manifest = read_json(path)
    require(manifest["schema"] == "plan05-integrated-r13.v1", "Manifest schema")
    require(manifest["scope"] == ["lf3", "lh"], "Pair-only scope")
    require(manifest["historical_q10"] == "FAIL" and manifest["q22"] == "HELD",
            "Historical dispositions must remain")
    require_pin_coverage(manifest, required_sources())
    for name, pin in manifest["source_pins"].items():
        require(digest(name) == pin, "Source changed: " + name)
    require(manifest["source_pins"].get(str(PREVIOUS / "owned_windows_job.py")) == BACKEND_SHA,
            "Retained ownership backend not bound")
    return manifest


def child_env():
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("PYTHON")}
    env.update(PYTHONHASHSEED="0", ATLAS_HS_DIR=str(T / "hs"))
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[key] = "1"
    return env


class JobPids(ctypes.Structure):
    _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                ("ids", ctypes.c_size_t * 256)]


def sample_job(job):
    """Read-only membership sample. A query failure never means an empty job."""
    buf = JobPids()
    if not job.k.QueryInformationJobObject(job.job, 3, ctypes.byref(buf),
                                         ctypes.sizeof(buf), None):
        raise OSError(ctypes.get_last_error(), "Job process-list query failed")
    require(buf.listed <= 256 and buf.assigned == buf.listed,
            "Incomplete or over-capacity process list")
    # Include this controller, which is outside its child job, in the guard.
    rss = psutil.Process().memory_info().rss
    for index in range(buf.listed):
        try:
            rss += psutil.Process(int(buf.ids[index])).memory_info().rss
        except psutil.NoSuchProcess:
            # A process may exit between the two observations.
            continue
    return rss, psutil.virtual_memory().available


def supervise(job, seconds, *, sample=sample_job, clock=time.monotonic,
              sleep=time.sleep, cleanup_seconds=10):
    start = clock()
    result = dict(finality="UNRESOLVED", exit_code=None, errors=[],
                  peak_sampled_tree_rss_bytes=0, free_low_bytes=None,
                  resource_measurement="sampled controller plus owned-job working set; not a hard memory bound")
    try:
        while True:
            snapshot = job.snapshot()
            result["last_observation"] = snapshot
            result["exit_code"] = snapshot["exit_code"]
            if snapshot["job"]["active"] == 0 and (
                    snapshot["exit_code"] is not None or not job.pi.process):
                result["finality"] = "COMPLETE"
                break
            rss, free = sample(job)
            result["peak_sampled_tree_rss_bytes"] = max(result["peak_sampled_tree_rss_bytes"], rss)
            result["free_low_bytes"] = free if result["free_low_bytes"] is None else min(free, result["free_low_bytes"])
            require(rss <= RSS_GUARD and free >= FREE_FLOOR, "In-run resource guard")
            require(clock() - start < seconds, "Operational deadline exceeded")
            sleep(0.25)
    except BaseException as failure:
        result["errors"].append(type(failure).__name__ + ": " + str(failure))
        try:
            result["termination"] = job.terminate_owned()
            end = clock() + cleanup_seconds
            while True:
                snapshot = job.snapshot()
                result["last_observation"] = snapshot
                result["exit_code"] = snapshot["exit_code"]
                if snapshot["job"]["active"] == 0 and (
                        snapshot["exit_code"] is not None or not job.pi.process):
                    result["finality"] = "COMPLETE"
                    break
                if clock() >= end:
                    result["errors"].append("Cleanup finality deadline exceeded")
                    break
                sleep(0.25)
        except BaseException as cleanup:
            result["errors"].append("cleanup: " + type(cleanup).__name__ + ": " + str(cleanup))
    result["wall_seconds"] = clock() - start
    result["passed"] = (result["finality"] == "COMPLETE" and
                        result["exit_code"] == 0 and not result["errors"])
    return result


def execute_owned(argv, out, name, seconds, env=None):
    backend = PREVIOUS / "owned_windows_job.py"
    require(digest(backend) == BACKEND_SHA, "Ownership backend changed")
    job_type = load_module("plan05_owned_backend", backend).WindowsJob
    record = dict(argv=[str(x) for x in argv], passed=False, finality="UNRESOLVED",
                  errors=[], log_final=False)
    job = None
    with (out / (name + ".stdout.log")).open("xb") as stdout, (
            out / (name + ".stderr.log")).open("xb") as stderr:
        try:
            job = job_type()
            job.start(record["argv"], HERE, env or child_env(), stdout, stderr)
            record.update(supervise(job, seconds))
        except BaseException:
            primary_errors = [*record["errors"], traceback.format_exc()]
            if job is not None:
                try:
                    job.terminate_owned()
                    record.update(supervise(job, 10))
                    record["passed"] = False
                    record["errors"] = primary_errors + record["errors"]
                except BaseException:
                    record["errors"] = primary_errors + [traceback.format_exc()]
            else:
                record["errors"] = primary_errors
        finally:
            if job is not None:
                record["ownership"] = dict(job.identity)
                try:
                    job.close()
                except BaseException:
                    record["passed"] = False
                    record["errors"].append(traceback.format_exc())
    record["log_final"] = record["finality"] == "COMPLETE"
    if record["log_final"]:
        record["log_sha256"] = {suffix: digest(out / (name + "." + suffix + ".log"))
                               for suffix in ("stdout", "stderr")}
    write_new(out / (name + ".process.json"), record)
    return record


def admission(manifest, available, env):
    estimate = manifest["capture_added_memory_mib"]
    require(type(estimate) in (int, float) and math.isfinite(estimate) and estimate > 0,
            "Missing justified capture-memory estimate")
    # Queue bookings are decimal GiB strings. Binary64 1.03 + 1 exceeds
    # binary64 2.03 by one ULP; that is not a real booking shortfall.
    prediction_exact = Decimal(str(BASELINE_GIB)) + Decimal(str(estimate)) / Decimal(1024)
    prediction = float(prediction_exact)
    # The queue rounds its formula to one decimal. Also enforce the unrounded formula.
    need = max(prediction * 1.2 + 2, round(prediction * 1.2 + 2, 1))
    require(Decimal(env.get("RUNQ_TICKET_GIB", "0")) >= prediction_exact,
            "Queue booking below need")
    require(float(env.get("RUNQ_MEM_NEED_GIB", "0")) >= round(prediction * 1.2 + 2, 1),
            "Missing queue admission")
    require(available / GIB >= need, "Free memory below capture start gate")
    return dict(predicted_peak_gib=prediction, start_gate_gib=need,
                free_gib_at_start=available / GIB,
                basis="matching q10 command observed 1.03 GiB plus estimated capture memory")


def claim_capture(manifest, manifest_sha, out, gate):
    """Consume one source-bound attempt; a continuation never resets old markers.

    A continuation authority is an owner-recorded direct user instruction, not
    inferred from a failed run. It names one output and all completed prior
    attempts. No retry loop or permission for another output is created.
    """
    authority = manifest.get("continuation_authority")
    record = dict(manifest_sha256=manifest_sha, out=str(out), admission=gate)
    if authority is None:
        marker = HERE / "D02-ATTEMPT.json"
        require(not any(HERE.glob("D02-ATTEMPT*.json")),
                "Scientific attempt already consumed; explicit continuation required")
    else:
        require(authority["scope"] == ["lf3", "lh"] and
                authority["maximum_attempts"] == 1 and
                authority["output"] == str(out),
                "Continuation must bind one pair attempt and its output")
        require(authority["user_instruction"] and authority["thread_id"],
                "Missing direct user continuation authority")
        prior = authority["prior_attempts"]
        require(prior and len(prior) == len({item["marker"] for item in prior}),
                "Missing or duplicated prior attempts")
        require({item["marker"] for item in prior} ==
                {path.name for path in HERE.glob("D02-ATTEMPT*.json")},
                "Prior attempt inventory changed")
        for item in prior:
            marker_path = HERE / item["marker"]
            require(marker_path.parent == HERE and
                    digest(marker_path) == item["marker_sha256"],
                    "Prior attempt marker changed")
            previous = read_json(marker_path)
            previous_out = Path(previous["out"]).resolve()
            require(previous_out.parent == HERE, "Prior output outside selected route")
            previous_result = previous_out / "result.json"
            require(digest(previous_result) == item["result_sha256"],
                    "Prior result changed")
            stages = read_json(previous_result)["stages"]
            require(all(stage["finality"] == "COMPLETE" and stage["log_final"] is True
                        for stage in stages), "Prior process finality unresolved")
        marker = HERE / ("D02-ATTEMPT-" + str(len(prior) + 1).zfill(2) + ".json")
        record["continuation_authority"] = authority
    # Exclusive creation is the dispatch barrier, including concurrent claims.
    write_new(marker, record)
    return marker


def consumer_queue_admission(selection, available, env, prediction=None):
    """Check real queue custody and the selected per-arm gate; never change a hold."""
    queue = read_json(T / "q/queue.json")
    ticket = next((item for item in queue["tickets"] if item["id"] == "q22"), None)
    require(not queue.get("hold") and ticket is not None
            and ticket["status"] == "running" and not ticket.get("ticket_hold"),
            "q22 is not running through its released queue ticket")
    require(ticket.get("quiet") is True and ticket.get("exclusive") is True
            and ticket.get("cores", 0) >= 7, "q22 needs the quiet exclusive seven-core route")
    ancestors = {process.pid for process in psutil.Process().parents()}
    require(ticket.get("runner_pid") in ancestors, "Current process is not owned by the q22 runner")
    resource = selection["resource_admission"]
    require(resource["baseline_observed_gib"] == BASELINE_GIB
            and type(resource["added_memory_mib"]) in (int, float)
            and isinstance(resource["basis"], str) and resource["basis"].strip(),
            "Consumer needs a bound observed baseline and justified additional estimate")
    require(resource["added_memory_mib"] > 0, "Positive booking preparation estimate required")
    if prediction is None:
        return dict(queue_ticket="q22", runner_pid=ticket["runner_pid"],
                    booking_preparation=resource, memory_gate="per-arm dynamic prediction required")
    peak, need = prediction["predicted_peak_gib"], prediction["required_start_gate_bytes"]
    require(type(peak) in (int, float) and math.isfinite(peak) and peak > 0
            and type(need) is int and need == math.ceil(max(peak * 1.2 + 2,
                round(peak * 1.2 + 2, 1)) * GIB), "Invalid dynamic memory gate")
    require(Decimal(env.get("RUNQ_TICKET_GIB", "0")) >= Decimal(str(peak)),
            "Queue booking below need")
    require(Decimal(env.get("RUNQ_MEM_NEED_GIB", "0")) >= Decimal(str(round(peak * 1.2 + 2, 1))),
            "Queue memory admission below need")
    require(available >= need, "Free memory below dynamic start gate")
    return dict(queue_ticket="q22", runner_pid=ticket["runner_pid"],
                predicted_peak_gib=peak, required_start_gate_bytes=need,
                free_bytes=available)


def consumer_plan(path, expected):
    require(digest(path) == expected, "Consumer selection digest differs")
    selection = read_json(path)
    for filename in ("proof_gate.py", "launch_adapter.py"):
        source = HERE / "consumer-repair" / filename
        require(selection["source_pins"].get(str(source.resolve())) == digest(source),
                "Consumer adapter/gate is not source-bound")
    adapter = load_module("plan05_selected_consumer_adapter", HERE / "consumer-repair/launch_adapter.py")
    return selection, adapter.build_plan(path, expected)


def run_consumer(args):
    """Execute the accepted successor with the existing owned process boundary."""
    selection, plan = consumer_plan(args.manifest, args.manifest_sha256)
    out = args.out.resolve()
    require(out == Path(plan["output"]).resolve() and out.is_relative_to(HERE)
            and len(str(out)) < 220,
            "Consumer output differs from its explicit authority")
    consumer_queue_admission(selection, psutil.virtual_memory().available, os.environ)
    for filename in ("consumer-repair/metrics.py", "ab_heat_r13.py"):
        source = HERE / filename
        require(selection["source_pins"].get(str(source.resolve())) == digest(source),
                "Consumer prediction source is not bound")
    metrics = load_module("plan05_consumer_metrics", HERE / "consumer-repair/metrics.py")
    writer = load_module("plan05_consumer_predictor", HERE / "ab_heat_r13.py")
    history = metrics.load_history(selection, writer)
    first = dict(plan["arms"][0], layout=str(T / "hs" / plan["arms"][0]["layout"]))
    prediction = metrics.predict_arm(selection, writer, first, history, [])
    gate = consumer_queue_admission(selection, psutil.virtual_memory().available,
                                    os.environ, prediction)
    out.mkdir()  # Exclusive claim: a partial attempt cannot be silently replayed.
    write_new(out / "attempt.json", dict(mode="consumer", manifest_sha256=args.manifest_sha256,
                                         queue_ticket="q22", admission=gate))
    result = dict(schema="plan12-consumer-route-result.r1", passed=False,
                  historical_q10="FAIL", stages=[], errors=[], arms=[])
    try:
        retain_selected_sources(selection, out)
        for arm_plan in plan["arms"]:
            consumer_plan_check = load_module(
                "plan05_running_consumer_gate", HERE / "consumer-repair/proof_gate.py")
            consumer_plan_check.validate_child(args.manifest, args.manifest_sha256,
                arm_plan["mode"], T / "hs" / arm_plan["layout"], out, arm_plan["index"])
            index = arm_plan["index"]
            summary = dict(arm=index, mode=arm_plan["mode"], label=arm_plan["label"],
                           layout=str(T / "hs" / arm_plan["layout"]))
            prediction = metrics.predict_arm(selection, writer, summary, history, result["arms"])
            summary.update(prediction)
            result["arms"].append(summary)
            started_wait = time.monotonic()
            # The later queue protocol bounds harness waiting to two minutes.
            # This is narrower than r8's retained 600-second predictor policy.
            summary["effective_wait_policy"] = dict(interval_seconds=15, maximum_seconds=120,
                basis="Current queue protocol's bounded harness wait")
            while True:
                free = psutil.virtual_memory().available
                elapsed = time.monotonic() - started_wait
                summary.update(metrics.start_observation(prediction, available_bytes=free,
                                                         waited_seconds=elapsed))
                if summary["start_gate_passed"] or elapsed >= 120:
                    break
                consumer_queue_admission(selection, free, os.environ)
                time.sleep(min(15, 120 - elapsed))
            arm_gate = consumer_queue_admission(selection, free, os.environ, prediction)
            summary["admission"] = arm_gate
            write_new(out / ("arm-" + str(index) + ".admission.json"),
                      dict(manifest_sha256=args.manifest_sha256, arm=index,
                           mode=summary["mode"], layout=summary["layout"],
                           prediction=prediction, admission=arm_gate))
            if summary["mode"] == "prof":
                (out / ("arm-" + str(index))).mkdir()
            busy_before = sum(value for key, value in psutil.cpu_times()._asdict().items()
                              if key != "idle")
            stage = execute_owned(arm_plan["argv"], out, "arm-" + str(index), 600,
                                  env=arm_plan["environment"])
            busy_after = sum(value for key, value in psutil.cpu_times()._asdict().items()
                             if key != "idle")
            result["stages"].append(stage)
            summary.update(exit_code=stage.get("exit_code"),
                           arm_wall_seconds=stage.get("wall_seconds"),
                           tree_peak_mib=stage.get("peak_sampled_tree_rss_bytes", 0) / (1 << 20))
            if not stage["passed"]:
                summary["stopped"] = "Owned process failed; no further arm dispatched"
            require(stage["passed"], "Consumer arm process/ownership failure")
            arm = read_json(out / ("arm-" + str(index) + ".json"))
            calls = arm["ab"]["calls"]
            summary.update(status=arm["status"], leaks=len(arm["ab"]["leaks"]),
                           used=[call["workers"] for call in calls],
                           fallback=[call["fallback"] for call in calls])
            require(arm["status"] == "PASS" and not arm["ab"]["leaks"]
                    and summary["used"] == [6, 6] and summary["fallback"] == [None, None],
                    "Consumer native validation or worker route failed")
            interpreter = arm["ab"]["interpreter"]
            require(type(interpreter.get("hash_randomization")) is int
                    and interpreter["hash_randomization"] == 0
                    and type(interpreter.get("worker_probe_hash_randomization")) is int
                    and interpreter["worker_probe_hash_randomization"] == 0,
                    "Consumer saved interpreter or worker hash-seed proof failed")
            require(arm["ab"]["consumer_selection"]["sha256"] == args.manifest_sha256,
                    "Consumer child did not retain the selected authority")
            summary.update(metrics.summary_metrics(arm, stage,
                           machine_busy_cpu_seconds=busy_after - busy_before))
            if summary["mode"] == "prof":
                profiles = sorted((out / ("arm-" + str(index))).glob("worker-*.prof"))
                observed = [path for path in profiles if path.is_file() and path.stat().st_size > 0]
                require(observed, "Profile arm produced no nonempty profile files")
                summary["profile_files"] = [
                    dict(path=str(path.relative_to(out)), bytes=path.stat().st_size,
                         sha256=digest(path)) for path in observed]
        write_new(out / "summary.json", dict(arms=result["arms"]))
        stage = execute_owned(plan["checker_argv"], out, "check-arms", 30)
        result["stages"].append(stage)
        with (out / "check-arms.txt").open("xb") as stream:
            stream.write((out / "check-arms.stdout.log").read_bytes())
        require(stage["passed"], "Existing 11-arm consumer rejected the run")
        consumer_plan_check.validate_selection(args.manifest, args.manifest_sha256)
        result["passed"] = True
    except BaseException:
        result["errors"].append(traceback.format_exc())
    if not (out / "summary.json").exists():
        write_new(out / "summary.json", dict(arms=result["arms"]))
    write_new(out / "result.json", result)
    print(json.dumps(dict(passed=result["passed"], result=str(out / "result.json"))), flush=True)
    return 0 if result["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("tests", "capture", "consumer"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "consumer":
        return run_consumer(args)
    manifest = verify_manifest(args.manifest, args.manifest_sha256)
    out = args.out.resolve()
    require(out.is_relative_to(HERE), "Evidence must stay under selected route")
    require(len(str(out)) < 220 and not out.exists(), "New bounded output path required")
    if args.mode == "capture":
        require(manifest["capture_ready"] is True, "Capture readiness incomplete")
        gate = admission(manifest, psutil.virtual_memory().available, os.environ)
        # Partial dispatch consumes this attempt too. Later continuation needs
        # a new explicit record and keeps every prior marker/result intact.
        claim_capture(manifest, args.manifest_sha256, out, gate)
    out.mkdir()
    write_new(out / "attempt.json", dict(mode=args.mode, manifest_sha256=args.manifest_sha256))
    result = dict(schema="plan05-route-result.v1", mode=args.mode, passed=False,
                  historical_q10="FAIL", q22="HELD", stages=[], errors=[])
    arms = []
    try:
        retain_selected_sources(manifest, out)
        if args.mode == "tests":
            command = [P, "-B", "-I", T / "q/runq.py", "small", "--cores", "1",
                       "--gib", "0.5", "--", P, "-B", "-s", "-P",
                       HERE / "run_tests_r13.py", "--out", out / "tests.json"]
            stage = execute_owned(command, out, "tests", 240)
            result["stages"].append(stage)
            require(stage["passed"], "Focused tests process failed")
            tests = read_json(out / "tests.json")
            require(tests["passed"] is True and tests["run"] == len(tests["expected"])
                    and tests["run"] > 0, "Incomplete/failed focused suite")
        else:
            result["admission"] = gate
            for index, layout in enumerate(("lf3", "lh")):
                verify_manifest(args.manifest, args.manifest_sha256)
                arm_gate = admission(manifest, psutil.virtual_memory().available, os.environ)
                summary = dict(arm=index, mode="proof", label=layout,
                               layout=str(T / "hs" / layout), admission=arm_gate)
                arms.append(summary)
                command = [P, "-B", "-s", "-P", HERE / "ab_heat_r13.py",
                           "child", "proof", T / "hs" / layout, out, str(index)]
                if "order_repair" in manifest:
                    command.extend(("--order-repair-selection", args.manifest, args.manifest_sha256))
                stage = execute_owned(command, out, "arm-" + str(index), 600)
                result["stages"].append(stage)
                summary.update(exit_code=stage.get("exit_code"),
                               arm_wall_seconds=stage.get("wall_seconds"),
                               tree_peak_mib=stage.get("peak_sampled_tree_rss_bytes", 0) / (1 << 20))
                if not stage["passed"]:
                    summary["stopped"] = "Process/observer failure; see retained arm logs"
                require(stage["passed"], "Pair arm incomplete/failed; no further dispatch")
                arm = read_json(out / ("arm-" + str(index) + ".json"))
                calls = arm["ab"]["calls"]
                summary.update(status=arm["status"], leaks=len(arm["ab"]["leaks"]),
                               used=[c["workers"] for c in calls],
                               fallback=[c["fallback"] for c in calls])
                require(arm["status"] == "PASS" and not arm["ab"]["leaks"],
                        "Arm proof/import isolation failure")
                require(len(calls) == 2 and all(c["workers"] == 6 and c["fallback"] is None
                                              for c in calls), "VOID-ENVIRONMENT: worker route differs")
            write_new(out / "summary.json", dict(arms=arms))
            checker = [P, "-B", "-s", "-P", T / "hs/scripts/check_arms.py", out, "2"]
            stage = execute_owned(checker, out, "check-arms", 30)
            result["stages"].append(stage)
            require(stage["passed"], "Existing arm consumer rejected pair")
            admission(manifest, psutil.virtual_memory().available, os.environ)
            verifier = [P, "-B", "-s", "-P", HERE / "verify_d02_r13.py",
                        "--pair", out, "--historical", T / "hs/evidence/h1c-r4a",
                        "--out", out / "verification.json"]
            stage = execute_owned(verifier, out, "verification", 120)
            result["stages"].append(stage)
            require(stage["passed"], "Correspondence verification failed; retain separate verdict")
        verify_manifest(args.manifest, args.manifest_sha256)
        result["passed"] = True
    except BaseException:
        result["errors"].append(traceback.format_exc())
    if args.mode == "capture" and not (out / "summary.json").exists():
        write_new(out / "summary.json", dict(arms=arms))
    write_new(out / "result.json", result)
    print(json.dumps(dict(passed=result["passed"], result=str(out / "result.json"))), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
