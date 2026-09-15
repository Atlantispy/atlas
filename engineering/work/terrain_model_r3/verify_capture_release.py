"""Bounded fresh-process capture release verification; no physical acceptance.

Run only after the complete R3 source closure is frozen. No predecessor or
installed file is written. A failed release directory is retained, never reused.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import io as string_io
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import time
import traceback
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
R2 = HERE.parent / "terrain_model_r2"
ALLOWED = REPO / "outputs" / "terrain-model-r3"
REFERENCE = REPO / "outputs" / "terrain-model-r2" / "reference-r2-03"
R2_REFERENCE_SHA256 = "7eea0a8f30e64c34025330e55a667d4d6a7a1f589dc75f1c5c7067daf89bf1ba"
R2_NORMAL_SHA256 = "25dcc0a9abaf6df1406f457e1107540d44bd5e6424549a7a705bb6d3287f70b3"
INSTALLED = Path("C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/06_Generator_System")
MIN_R3_TESTS = 102
R2_TESTS = 239
TIMEOUT_SECONDS = 60
MAX_FILE_BYTES = 16 * 1024 * 1024
SOURCE_SUFFIXES = {".py", ".json", ".md", ".ps1"}
SCENARIOS = ("closed_column_settling", "mixed_phase_overflow", "flowing_pool_tracer",
             "bed_only_displacement", "unequal_concentrations_nested_pools", "simultaneous_sill_phase_spill")
R3_TEST_MODULES = {"test_capture", "test_phase_storage", "test_settling",
                   "test_capture_workflow", "test_capture_topology", "test_coupled_equations"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    canonical(value)  # Also rejects exponent overflow such as 1e999.
    return value


def unlinked(path):
    raw = os.fspath(path)
    # This local-only release accepts neither network/device namespaces nor ADS.
    if raw.replace("/", "\\").startswith("\\\\"):
        raise ValueError("network/device paths are not release paths")
    candidate = Path(raw).absolute()
    if ".." in candidate.parts or any(":" in part for part in candidate.parts[1:]):
        raise ValueError("unsafe source/output path")
    for current in (candidate, *candidate.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("linked/reparse path rejected: " + str(current))
    return candidate.resolve(strict=False)


def read_bytes(path):
    path = unlinked(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError("bounded regular file required: " + str(path))
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    after = path.stat()
    if len(raw) > MAX_FILE_BYTES or (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("file changed or exceeded size bound during read: " + str(path))
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_pin(path):
    raw = read_bytes(path)
    return {"bytes": len(raw), "sha256": digest(raw)}


def write_new(root, path, value):
    root, path = unlinked(root), unlinked(path)
    if not path.is_relative_to(root) or path == root:
        raise ValueError("release write escapes its reserved directory")
    raw = canonical(value)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("release evidence exceeds bounded file size")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if read_bytes(path) != raw:
        raise ValueError("release evidence readback differs")


def safe_relative(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("invalid relative source name")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts) or path.as_posix() != name:
        raise ValueError("noncanonical relative source name")
    return Path(*path.parts)


def source_files(directory):
    """Bounded existing source subtree only; do not traverse linked directories."""
    directory = unlinked(directory)
    found = {}
    for base, dirs, names in os.walk(directory, followlinks=False):
        for name in dirs:
            unlinked(Path(base) / name)
        for name in names:
            path = Path(base) / name
            if path.suffix.lower() in SOURCE_SUFFIXES:
                relative = path.relative_to(directory).as_posix()
                if relative.casefold() in {x.casefold() for x in found}:
                    raise ValueError("duplicate case-insensitive source identity")
                found[relative] = file_pin(path)
        if len(found) > 256:
            raise ValueError("source closure exceeds this bounded verifier")
    return found


def predecessor_pins():
    ref_raw = read_bytes(REFERENCE / "REFERENCE_VERIFICATION.json")
    normal_raw = read_bytes(REFERENCE / "NORMAL_WORKFLOW_VERIFICATION.json")
    if digest(ref_raw) != R2_REFERENCE_SHA256 or digest(normal_raw) != R2_NORMAL_SHA256:
        raise ValueError("frozen R2 release record identity changed")
    ref, normal = parse_json(ref_raw), parse_json(normal_raw)
    if (ref["status"] != "BOUNDED_REFERENCE_RELEASE_VERIFIED_NOT_WHOLE_MODEL_ACCEPTANCE"
            or ref["tests_per_process"] != [R2_TESTS, R2_TESTS]
            or ref["production_authorised"] is not False or ref["canon_changed"] is not False
            or normal["status"] != "NORMAL_SYNTHETIC_WORKFLOW_VERIFIED"
            or normal["production_authorised"] is not False or normal["canon_changed"] is not False):
        raise ValueError("R2 evidence scope/status is not the frozen reference")
    expected = {}
    for row in ref["source_closure"]:
        if set(row) != {"name", "bytes", "sha256"} or type(row["bytes"]) is not int or row["bytes"] <= 0:
            raise ValueError("malformed predecessor closure row")
        safe_relative(row["name"])
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) or row["name"] in expected:
            raise ValueError("malformed/duplicate predecessor source pin")
        expected[row["name"]] = {"bytes": row["bytes"], "sha256": row["sha256"]}
    if len(expected) != 41 or source_files(R2) != expected:
        raise ValueError("full frozen local R2 source closure differs")
    installed = normal["installed_sources_sha256"]
    if not isinstance(installed, dict) or len(installed) != 20:
        raise ValueError("installed R2 source inventory changed")
    verified = {}
    for name, expected_sha in installed.items():
        path = unlinked(name)
        if not path.is_relative_to(unlinked(INSTALLED)) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise ValueError("invalid installed predecessor binding")
        pin = file_pin(path)
        if pin["sha256"] != expected_sha:
            raise ValueError("installed R2 source drift: " + name)
        verified[name] = pin
    return {"reference_record": {"path": str(REFERENCE / "REFERENCE_VERIFICATION.json"),
                                 "sha256": R2_REFERENCE_SHA256},
            "normal_workflow_record": {"path": str(REFERENCE / "NORMAL_WORKFLOW_VERIFICATION.json"),
                                       "sha256": R2_NORMAL_SHA256},
            "local_source_closure": expected, "installed_source_pins": verified}


def snapshot():
    return {"r3_source_closure": source_files(HERE), "predecessor": predecessor_pins()}


def load_model(expected):
    # First validate all local/installed predecessor bytes before local imports.
    if snapshot() != expected:
        raise ValueError("source closure changed before imports")
    import capture
    import capture_fixtures
    import capture_workflow
    if capture_workflow.source_pins() != capture_workflow.LOADED_SOURCE_PINS or snapshot() != expected:
        raise ValueError("source closure changed across model imports")
    return capture, capture_fixtures, capture_workflow


def loaded_sources(expected):
    result = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).absolute()
        for base, prefix, pins in ((HERE, "R3/", expected["r3_source_closure"]),
                                  (R2, "R2/", expected["predecessor"]["local_source_closure"])):
            if path.is_relative_to(base):
                relative = path.relative_to(base).as_posix()
                if relative not in pins or file_pin(path) != pins[relative]:
                    raise ValueError("unbound/drifted imported module: " + name)
                result[name] = {"source": prefix + relative, **pins[relative]}
    if not result:
        raise ValueError("empty imported local source inventory")
    return result


def test_ids(suite):
    result = []
    for test in suite:
        result.extend(test_ids(test) if isinstance(test, unittest.TestSuite) else [test.id()])
    return result


def run_tests(directory, minimum, required_modules=(), *, exact=None):
    loader = unittest.TestLoader()
    suite = loader.discover(str(directory), pattern="test_*.py", top_level_dir=str(directory))
    inventory = test_ids(suite)
    stream = string_io.StringIO()
    tested = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    modules = {name.split(".", 1)[0] for name in inventory}
    discovered_files = {p.stem for p in directory.glob("test_*.py")}
    passed = (tested.testsRun >= minimum and (exact is None or tested.testsRun == exact)
              and tested.testsRun == len(inventory) and len(set(inventory)) == len(inventory)
              and set(required_modules) <= modules and discovered_files <= modules
              and tested.wasSuccessful() and not tested.skipped
              and not tested.expectedFailures and not tested.unexpectedSuccesses and not loader.errors)
    return {"status": "PASS" if passed else "FAIL", "run": tested.testsRun,
            "minimum_required": minimum, "exact_required": exact, "inventory": inventory,
            "discovered_modules": sorted(modules), "discovered_test_files": sorted(discovered_files),
            "failures": len(tested.failures), "errors": len(tested.errors), "skipped": len(tested.skipped),
            "expected_failures": len(tested.expectedFailures), "unexpected_successes": len(tested.unexpectedSuccesses),
            "loader_errors": loader.errors, "log": stream.getvalue()}


def require_test_success(report):
    if report["status"] != "PASS" or report["run"] < report["minimum_required"] or report["run"] <= 0:
        raise RuntimeError("reviewed tests failed, skipped or incomplete; retained test report contains details")


def peak_working_set():
    if sys.platform != "win32":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def products(directory):
    directory = unlinked(directory)
    result = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            raise ValueError("unexpected nested/nonfile generation product")
        result[path.name] = file_pin(path)
    if not {"RECIPE.json", "RESULT.json", "RECEIPT.json"} <= set(result):
        raise ValueError("incomplete generation product inventory")
    return result


def exact_products(first, second):
    a, b = products(first), products(second)
    if a != b or any(read_bytes(first / name) != read_bytes(second / name) for name in a):
        raise ValueError("complete generation bytes differ: " + str(first) + " / " + str(second))
    return a


def tracer_refinement(capture, fixtures):
    rows = []
    expected = .1 * -math.expm1(-.1)
    for steps in (10, 20, 40):
        recipe = deepcopy(next(x for x in fixtures.suite() if x["scenario_id"] == "flowing_pool_tracer"))
        recipe["forcing"].update(steps=steps, dt_years=1. / steps)
        state, diagnostics = capture.advance(capture.CaptureState(**recipe["state"]), **recipe["forcing"])
        actual = math.fsum(state.suspended_solid_m3)
        error = abs(actual - expected)
        if not math.isfinite(error) or error <= 0:
            raise ValueError("tracer error is not a resolved positive refinement error")
        rows.append({"steps": steps, "dt_years": 1. / steps, "actual_suspension_m3": actual,
                     "absolute_error_m3": error, "liquid_ledger": diagnostics["liquid_ledger"],
                     "solid_ledger": diagnostics["solid_ledger"]})
    orders = [math.log2(a["absolute_error_m3"] / b["absolute_error_m3"]) for a, b in zip(rows, rows[1:])]
    minimum = capture.CONTRACT["minimum_smooth_convergence_order"]
    if any(not math.isfinite(order) or order < minimum for order in orders):
        raise ValueError("analytical tracer refinement misses frozen minimum order")
    return {"analytic_suspension_m3": expected, "measurements": rows,
            "observed_global_orders": orders, "minimum_declared_order": minimum,
            "physical_validation": False}


def old_near_flat_rejection(workflow):
    spec = importlib.util.spec_from_file_location("_capture_release_r2_fixtures", R2 / "fixtures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    recipe = module.near_flat_capture_regression()
    try:
        workflow.io.execute(recipe)
    except ValueError as exc:
        if "relative link relief" not in str(exc):
            raise
        return {"status": "EXPECTED_R2_REJECTION_PRESERVED", "reason": str(exc),
                "canonical_recipe_sha256": digest(canonical(recipe)),
                "workflow_sha256": file_pin(R2 / "workflow.py")["sha256"],
                "near_flat_shoreline_capture_completed": False}
    raise ValueError("R2 near-flat rejection changed; explicit review required")


def assert_model_unchanged(expected, workflow, imported_pins):
    if (snapshot() != expected or workflow.source_pins() != imported_pins
            or workflow.LOADED_SOURCE_PINS != imported_pins):
        raise ValueError("source bytes/import-loaded binding changed during release")
    return loaded_sources(expected)


def worker(root, name):
    started = time.perf_counter()
    control = parse_json(read_bytes(root / "RUN_CONTROL.json"))
    if control["schema"] != "diadem.terrain.capture.release-control.r3" or control["minimum_r3_tests"] != MIN_R3_TESTS:
        raise ValueError("unrecognised release control")
    expected = control["source_snapshot"]
    capture, fixtures, workflow = load_model(expected)
    imported_pins = deepcopy(workflow.LOADED_SOURCE_PINS)
    loaded_before = loaded_sources(expected)
    if name == "r2":
        sys.path.insert(0, str(R2))
        tests = run_tests(R2, R2_TESTS, exact=R2_TESTS)
        write_new(root, root / "TESTS-r2.json", tests)
        require_test_success(tests)
        unsupported = old_near_flat_rejection(workflow)
        loaded_after = assert_model_unchanged(expected, workflow, imported_pins)
        report = {"status": "PASS", "worker": name, "tests_file": "TESTS-r2.json", "test_count": tests["run"],
                  "known_unsupported_capture": unsupported}
    else:
        tests = run_tests(HERE, MIN_R3_TESTS, R3_TEST_MODULES, exact=MIN_R3_TESTS)
        write_new(root, root / ("TESTS-" + name + ".json"), tests)
        require_test_success(tests)
        assert_model_unchanged(expected, workflow, imported_pins)
        recipes = fixtures.suite()
        if tuple(x["scenario_id"] for x in recipes) != SCENARIOS:
            raise ValueError("the six canonical fixture identities/order changed")
        if set(p.name for p in (root / "recipes").iterdir()) != {x + ".json" for x in SCENARIOS}:
            raise ValueError("foreign/missing release recipes")
        directory = root / name
        directory.mkdir(exist_ok=False)
        measurements, inventories = [], {}
        for recipe in recipes:
            scenario = recipe["scenario_id"]
            source = root / "recipes" / (scenario + ".json")
            if read_bytes(source) != canonical(recipe):
                raise ValueError("release recipe is not the canonical frozen fixture")
            output = directory / scenario
            before = time.perf_counter(); committed = workflow.run(source, output)
            commit_seconds = time.perf_counter() - before
            original = products(output)
            before = time.perf_counter(); reused = workflow.run(source, output, resume=True)
            reuse_seconds = time.perf_counter() - before
            if (committed["status"] != "COMMITTED_CAPTURE_REFERENCE" or reused["status"] != "VERIFIED_CAPTURE_REUSE"
                    or committed["generation_id"] != reused["generation_id"] or original != products(output)):
                raise ValueError("commit/reuse did not preserve complete generation")
            inventories[scenario] = original
            measurements.append({"scenario": scenario, "commit_wall_seconds": commit_seconds,
                                 "verified_reuse_wall_seconds": reuse_seconds,
                                 "output_bytes": sum(p["bytes"] for p in original.values()),
                                 "generation_id": committed["generation_id"], "reuse_status": reused["status"]})
        recovery = directory / "interrupted-tracer"
        tracer_source = root / "recipes" / "flowing_pool_tracer.json"
        try:
            workflow.run(tracer_source, recovery, interrupt_after_step=10)
        except RuntimeError as exc:
            if str(exc) != "injected interruption after phase-state checkpoint":
                raise
        else:
            raise AssertionError("step10 checkpoint interruption did not happen")
        if recovery.exists():
            raise AssertionError("interrupted generation was committed")
        partials = list(directory.glob("interrupted-tracer.pending-*"))
        if len(partials) != 1 or {p.name for p in partials[0].iterdir()} != {"RECIPE.json", "CHECKPOINT-000010.json"}:
            raise ValueError("interruption did not retain exactly the first durable checkpoint")
        first_checkpoint = file_pin(partials[0] / "CHECKPOINT-000010.json")
        recovered = workflow.run(tracer_source, recovery, resume=True)
        if recovered["status"] != "COMMITTED_CAPTURE_REFERENCE":
            raise ValueError("recovery failed to commit")
        recovered_inventory = exact_products(recovery, directory / "flowing_pool_tracer")
        if recovered_inventory["CHECKPOINT-000010.json"] != first_checkpoint or partials[0].exists():
            raise ValueError("recovery lost/changed its first checkpoint or left the partial tree")
        refinement = tracer_refinement(capture, fixtures)
        import test_coupled_equations
        coupled = test_coupled_equations.measure()
        orders = coupled["observed_global_orders"]
        if (len(orders) != 2 or coupled["minimum_declared_order"] != capture.CONTRACT["minimum_smooth_convergence_order"]
                or any(not math.isfinite(x) or x < capture.CONTRACT["minimum_smooth_convergence_order"] for x in orders)):
            raise ValueError("coupled independent ODE refinement misses frozen order")
        unsupported = old_near_flat_rejection(workflow)
        loaded_after = assert_model_unchanged(expected, workflow, imported_pins)
        report = {"status": "PASS", "worker": name, "tests_file": "TESTS-" + name + ".json", "test_count": tests["run"],
                  "measurements": measurements, "complete_products": inventories,
                  "results_sha256": {key: value["RESULT.json"]["sha256"] for key, value in inventories.items()},
                  "recovery": {"status": "EXACT_COMPLETE_PRODUCTS_AFTER_STEP10_INTERRUPTION", "interrupted_at_step": 10,
                               "retained_checkpoint": first_checkpoint, "complete_products": recovered_inventory,
                               "mode": "independent reconstruction verifies checkpoints; not accelerated state-only restart"},
                  "tracer_refinement": refinement, "coupled_equation_refinement": coupled,
                  "known_unsupported_capture": unsupported}
    report.update(source_snapshot=expected, import_loaded_source_pins=imported_pins,
                  loaded_local_modules_before=loaded_before, loaded_local_modules_after=loaded_after,
                  worker_wall_seconds=time.perf_counter() - started, peak_working_set_bytes=peak_working_set(),
                  python=sys.version, executable=str(Path(sys.executable).resolve()), platform=platform.platform(),
                  resource_boundary="Worker Python lifetime peak includes tests, hashing, receipts, checkpoint recovery and analytical checks; excludes child-process working sets and temporary test output bytes. Parent subprocess wall includes process startup/shutdown. Not standalone terrain peak or an OS memory quota.",
                  optimisation_speedup_percent=None, physical_acceptance=False, production_authorised=False, canon_changed=False)
    write_new(root, root / ("PROCESS-" + name + ".json"), report)


def invoke(root, name):
    out, err = root / (name + ".stdout.txt"), root / (name + ".stderr.txt")
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--output", str(root), "--worker", name]
    before = time.perf_counter()
    with out.open("xb") as stdout, err.open("xb") as stderr:
        try:
            completed = subprocess.run(command, cwd=REPO, stdout=stdout, stderr=stderr,
                                       timeout=TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            write_new(root, root / ("TIMEOUT-" + name + ".json"),
                      {"worker": name, "status": "FAIL", "timeout_seconds": TIMEOUT_SECONDS})
            raise
    record = {"worker": name, "command": command, "wall_seconds": time.perf_counter() - before,
              "timeout_seconds": TIMEOUT_SECONDS, "exit_code": completed.returncode,
              "stdout": file_pin(out), "stderr": file_pin(err)}
    write_new(root, root / ("SUBPROCESS-" + name + ".json"), record)
    if completed.returncode != 0:
        raise RuntimeError("fresh worker failed; see retained logs: " + name)
    report = parse_json(read_bytes(root / ("PROCESS-" + name + ".json")))
    if report["status"] != "PASS":
        raise ValueError("worker did not report an explicit PASS")
    return record, report


def release(root):
    expected = snapshot()
    capture, fixtures, workflow = load_model(expected)
    imported_pins = deepcopy(workflow.LOADED_SOURCE_PINS)
    recipes = fixtures.suite()
    if tuple(recipe["scenario_id"] for recipe in recipes) != SCENARIOS:
        raise ValueError("unexpected canonical fixture set")
    (root / "recipes").mkdir()
    write_new(root, root / "RUN_CONTROL.json", {"schema": "diadem.terrain.capture.release-control.r3",
              "minimum_r3_tests": MIN_R3_TESTS, "r2_exact_tests": R2_TESTS, "source_snapshot": expected,
              "worker_timeout_seconds": TIMEOUT_SECONDS, "physical_acceptance": False, "production_authorised": False})
    for recipe in recipes:
        write_new(root, root / "recipes" / (recipe["scenario_id"] + ".json"), recipe)
    processes = []
    records = []
    for name in ("r3-01", "r3-02", "r2"):
        process, report = invoke(root, name)
        processes.append(process); records.append(report)
        assert_model_unchanged(expected, workflow, imported_pins)
    first, second, r2 = records
    for key in ("complete_products", "results_sha256", "recovery", "tracer_refinement", "coupled_equation_refinement",
                "known_unsupported_capture", "source_snapshot", "import_loaded_source_pins", "loaded_local_modules_after"):
        if canonical(first[key]) != canonical(second[key]):
            raise ValueError("fresh-worker evidence parity differs: " + key)
    test_a = parse_json(read_bytes(root / first["tests_file"]))
    test_b = parse_json(read_bytes(root / second["tests_file"]))
    if test_a["inventory"] != test_b["inventory"]:
        raise ValueError("fresh processes discovered different tests")
    for scenario in SCENARIOS:
        exact_products(root / "r3-01" / scenario, root / "r3-02" / scenario)
    exact_products(root / "r3-01" / "interrupted-tracer", root / "r3-02" / "interrupted-tracer")
    if canonical(first["known_unsupported_capture"]) != canonical(r2["known_unsupported_capture"]):
        raise ValueError("fresh R2/R3 processes disagree on retained near-flat rejection")
    loaded_after = assert_model_unchanged(expected, workflow, imported_pins)
    report = {"schema": "diadem.terrain.capture.release-verification.r3",
              "status": "BOUNDED_CAPTURE_REFERENCE_VERIFIED_NOT_PHYSICAL_ACCEPTANCE",
              "fresh_r3_workers": 2, "r3_tests_per_worker": [first["test_count"], second["test_count"]],
              "fresh_r2_test_workers": 1, "r2_test_count": r2["test_count"],
              "reviewed_r3_test_inventory": test_a["inventory"], "canonical_scenarios": list(SCENARIOS),
              "exact_result_parity": True, "exact_complete_product_parity": True,
              "step10_recovery_complete_product_parity": True, "source_snapshot_before_and_after": expected,
              "import_loaded_source_pins": imported_pins, "parent_loaded_modules_after": loaded_after,
              "tracer_refinement": first["tracer_refinement"], "coupled_equation_refinement": first["coupled_equation_refinement"],
              "known_unsupported_capture": first["known_unsupported_capture"], "subprocesses": processes,
              "worker_peak_working_set_bytes": [r["peak_working_set_bytes"] for r in records],
              "resource_boundary": first["resource_boundary"], "optimisation_speedup_percent": None,
              "physical_acceptance": False, "shoreline_capture_acceptance": False,
              "production_authorised": False, "canon_changed": False,
              "scope": "Prescribed-port nonporous phase storage/settling reference only; native wet disconnection rejects. No recovered near-flat dry-channel/shoreline completion or new Diadem terrain."}
    write_new(root, root / "REFERENCE_VERIFICATION.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", choices=("r3-01", "r3-02", "r2"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = unlinked(args.output)
    if root.parent != unlinked(ALLOWED) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", root.name):
        raise ValueError("release output must be a named direct child of outputs/terrain-model-r3")
    if args.worker:
        if not root.is_dir():
            raise ValueError("worker requires a parent-reserved release directory")
        worker(root, args.worker)
        return
    if root.exists():
        raise FileExistsError("release output already exists; retain it and choose a new name")
    # Creating only this approved output container is allowed; predecessor roots
    # and installed paths are read-only throughout this verifier.
    unlinked(ALLOWED).mkdir(parents=True, exist_ok=True)
    # Reservation happens outside the failure handler: a same-name collision
    # must not add a FAILURE receipt to a directory owned by another invocation.
    root.mkdir(exist_ok=False)
    try:
        report = release(root)
    except BaseException as exc:
        if root.is_dir() and not (root / "FAILURE.json").exists():
            write_new(root, root / "FAILURE.json", {"status": "FAIL", "error_type": type(exc).__name__,
                      "message": str(exc), "traceback": traceback.format_exc(), "production_authorised": False})
        raise
    print(json.dumps({key: report[key] for key in ("status", "fresh_r3_workers", "r3_tests_per_worker", "r2_test_count",
                     "canonical_scenarios", "exact_complete_product_parity", "step10_recovery_complete_product_parity")}, indent=2))


if __name__ == "__main__":
    main()
