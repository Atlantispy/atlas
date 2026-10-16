"""One fresh-process Step 5B measurement of the unchanged saved synthetic fixture.

Calls test_mesh_v3.cold unchanged. No fixture production, historical stores,
simulation, polling, repeated runs, or changed guard/cancellation behaviour.
"""
from __future__ import annotations

import argparse
import builtins
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import sys
from time import perf_counter
import traceback


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPONENTS = ROOT / "compact-geometry-r1"
TASK = ROOT.parents[3]
FIXTURE = TASK / "_t/mesh-v3-large-step5-20261015"
BASELINE = ROOT / "test-results/step5-mesh-partition.json"
RUNTIME = ROOT.parent / "runtime-integration-r1/runtime-src"


def digest(path):
    with path.open("rb") as source:
        value = sha256()
        for block in iter(lambda: source.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def snapshot(paths):
    return {str(path): {"bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(set(paths))}


def fixture_snapshot():
    paths = list(FIXTURE.iterdir())
    if any(not path.is_file() for path in paths):
        raise ValueError("Saved fixture must contain files only")
    return snapshot(paths)


def source_paths(baseline):
    paths = {COMPONENTS / name for name in baseline["source_sha256"]}
    paths.update(COMPONENTS / item["name"]
                 for item in baseline["evidence_bindings"]["unchanged"])
    paths.update(Path(item["path"])
                 for item in baseline["evidence_bindings"]["dependencies"])
    paths.update((Path(__file__).resolve(), COMPONENTS / "test_mesh_v3.py"))
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename:
            path = Path(filename).resolve()
            if path.suffix == ".py" and any(path.is_relative_to(root)
                                            for root in (COMPONENTS, ROOT, RUNTIME)):
                paths.add(path)
    return paths


def physical_bytes(files, *, include_receipt=False):
    return sum(row["bytes"] for name, row in files.items()
               if include_receipt or Path(name).name != "mesh-v3-reference.json")


class Tee:
    def __init__(self, saved, stream):
        self.saved, self.stream = saved, stream

    def write(self, text):
        self.saved.write(text)
        self.stream.write(text)
        return len(text)

    def flush(self):
        self.saved.flush()
        self.stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True,
                        help="New, nonexistent directory directly inside probes/step5b")
    arguments = parser.parse_args()
    output = Path(arguments.output_dir).resolve()
    if output.parent != HERE or output.exists():
        parser.error("Output must be a new directory directly inside probes/step5b")
    output.mkdir()
    result = {"status": "INCOMPLETE", "started_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "One saved synthetic large-fixture fresh-process cold reopen",
              "fixture": str(FIXTURE), "output": str(output),
              "historical_database_opened": False, "interval_two_advanced": False,
              "fixture_rebuilt": False}
    code = 1
    stdout = sys.stdout
    with (output / "stdout.log").open("x", encoding="utf8") as saved_stdout, \
            (output / "stderr.log").open("x", encoding="utf8") as saved_stderr:
        log = Tee(saved_stdout, stdout)
        with redirect_stdout(log), redirect_stderr(Tee(saved_stderr, sys.stderr)):
            try:
                baseline = json.loads(BASELINE.read_text(encoding="utf8"))
                fixture_receipt = json.loads((FIXTURE / "mesh-v3-reference.json").read_text(encoding="utf8"))
                result["baseline_binding"] = snapshot([BASELINE])
                result["fixture_before"] = fixture_snapshot()
                result["fixture_reference"] = fixture_receipt["reference"]
                result["baseline_large_fixture"] = baseline["measurements"]["large_fixture"]
                sys.path.insert(0, str(COMPONENTS))
                import test_mesh_v3 as harness
                import numpy
                import psutil
                process = psutil.Process()
                result["sources_before"] = snapshot(source_paths(baseline))
                result["environment"] = {
                    "python": sys.version, "executable": str(Path(sys.executable).resolve()),
                    "executable_sha256": digest(Path(sys.executable)),
                    "platform": platform.platform(), "numpy_version": numpy.__version__,
                    "psutil_version": psutil.__version__,
                    "thread_environment": {name: os.environ.get(name) for name in
                        ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                         "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "PYTHONHASHSEED")}}
                result["configuration"] = {
                    "call": "test_mesh_v3.cold(fixture/catalog.json, saved_reference, progress=True)",
                    "run_budget_bytes": 1 << 30, "retained_open_gate_bytes": 64 << 20,
                    "cooperative_watchdog_seconds": 600, "existing_progress_seconds": 30,
                    "fixed_contract_limits": baseline["limits"],
                    "cache_state": "Fresh process; OS file-cache state uncontrolled, as in baseline",
                    "measurement_boundary": "Original harness cold-open timer; catalogue opening precedes it",
                    "memory": "Parent process checkpoint RSS/private bytes; OS peaks cover whole process lifetime",
                    "instrumentation": "Only existing cold-start, phase-complete/failed, cold-open/supports prints get memory readings; hook cost measured separately",
                    "disk": "File lengths, not allocated filesystem clusters; catalog + sqlite + lock excludes reference receipt"}
                result["configuration_sha256"] = sha256(json.dumps(
                    result["configuration"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                result["events"] = []
                observations = []

                def checkpoint_print(*values, **kwargs):
                    started = perf_counter()
                    event = json.loads(values[0]) if len(values) == 1 and isinstance(values[0], str) else None
                    if isinstance(event, dict):
                        stage = event.get("stage", "")
                        if stage in ("cold-start", "cold-open", "cold-supports") or stage.endswith(("-complete", "-failed")):
                            memory = process.memory_info()._asdict()
                            event["process_memory"] = {key: memory.get(key) for key in
                                ("rss", "private", "peak_wset", "peak_pagefile")}
                        result["events"].append(event)
                        values = (json.dumps(event, sort_keys=True),)
                    builtins.print(*values, **dict(kwargs, file=log))
                    observations.append(perf_counter() - started)

                # Patch only this diagnostic module's print name. cold() and its
                # validation, cancellation, page/retained budgets are unchanged.
                harness.print = checkpoint_print
                call_started = perf_counter()
                try:
                    harness.cold(FIXTURE / "catalog.json", fixture_receipt["reference"], progress=True)
                finally:
                    result["whole_call_seconds"] = perf_counter() - call_started
                    del harness.print
                    result["checkpoint_hook_seconds"] = sum(observations)
                    result["checkpoint_hook_calls"] = len(observations)
                result["zero_reservations_after_close"] = True  # cold() asserts before returning
                result["sources_after"] = snapshot(source_paths(baseline))
                result["fixture_after"] = fixture_snapshot()
                result["fixture_unchanged"] = result["fixture_before"] == result["fixture_after"]
                result["sources_unchanged_during_run"] = all(
                    result["sources_after"].get(path) == value
                    for path, value in result["sources_before"].items())
                if not result["fixture_unchanged"] or not result["sources_unchanged_during_run"]:
                    raise RuntimeError("Fixture or source identity changed during measurement")
                opened = [event for event in result["events"] if event.get("stage") == "cold-open"]
                if len(opened) != 1:
                    raise RuntimeError("Expected exactly one completed cold-open")
                old = next(row for row in reversed(result["baseline_large_fixture"]["cold_attempts"])
                           if row["status"] == "PASS")
                current = opened[0]
                result["comparison"] = {
                    "baseline_seconds": old["seconds"], "candidate_seconds": current["seconds"],
                    "elapsed_delta_seconds": current["seconds"] - old["seconds"],
                    "elapsed_reduction_percent": 100 * (1 - current["seconds"] / old["seconds"]),
                    "baseline_retained_after_open_bytes": old["retained_after_open_bytes"],
                    "candidate_retained_after_open_bytes": current["held_bytes"],
                    "retained_delta_bytes": current["held_bytes"] - old["retained_after_open_bytes"],
                    "process_ram_baseline": None,
                    "process_ram_comparison": "NOT_MEASURED: baseline has no RSS/private reading",
                    "baseline_catalog_store_bytes": result["baseline_large_fixture"]["catalog_and_store_bytes"],
                    "candidate_catalog_store_bytes": physical_bytes(result["fixture_after"]),
                    "catalog_store_delta_bytes": physical_bytes(result["fixture_after"]) - result["baseline_large_fixture"]["catalog_and_store_bytes"],
                    "candidate_all_fixture_bytes": physical_bytes(result["fixture_after"], include_receipt=True),
                    "timing_caveat": "Candidate includes measured checkpoint-hook cost; raw observed time is not adjusted. OS cache uncontrolled."}
                result["status"] = "PASS"
                code = 0
            except BaseException as error:
                result["status"] = "FAIL"
                result["error"] = {"type": type(error).__name__, "message": str(error)}
                traceback.print_exc()
                if "fixture_before" in result:
                    try:
                        result["fixture_after"] = fixture_snapshot()
                        result["fixture_unchanged"] = result["fixture_before"] == result["fixture_after"]
                    except BaseException as inspection_error:
                        result["post_failure_inspection_error"] = repr(inspection_error)
            finally:
                result["finished_utc"] = datetime.now(timezone.utc).isoformat()
                with (output / "measurement.json").open("x", encoding="utf8") as destination:
                    json.dump(result, destination, indent=2, sort_keys=True)
                    destination.write("\n")
                builtins.print(json.dumps({"status": result["status"],
                    "measurement": str(output / "measurement.json")}), file=log, flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
