"""Bounded consumer runtime controls. Native bootstraps dispatch no face tasks."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
PYTHON = T / ".r44-env/Scripts/python.exe"
ARTIFACTS = HERE / "worker-test-artifacts"
SPEC = importlib.util.spec_from_file_location("plan05_consumer_worker_runtime", HERE / "worker_runtime.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def synthetic_parallel():
    return SimpleNamespace(
        __file__=str(T / "hs/lf3/helpers/private_heat_functionals_parallel_r1.py"),
        _runtime=lambda: {"flags": ("synthetic",), "backend": "synthetic"},
    )


FLAGS = SimpleNamespace(dont_write_bytecode=1, no_user_site=1, safe_path=True,
                        hash_randomization=0, ignore_environment=0, isolated=0)


def native_case(layout, mode, directory):
    """The real native start/select/admit/stop handshake, with zero face tasks."""
    pins = R.required_source_pins(layout, mode)
    parallel = R.load_selected(layout, mode=mode, source_pins=pins)
    import private_heat_functionals_kernel_r5 as kernel
    from atlas_tectonics.resources import WorkBudget
    record = {
        "layout": layout, "mode": mode, "scientific_face_tasks_sent": 0,
        "source_pins": pins, "runtime": R.enable_and_probe(parallel, mode=mode, source_pins=pins),
    }
    budget = WorkBudget(6 << 30)
    meter = parallel.METER.open(budget, name="consumer-worker-empty-bootstrap")
    if meter is None:
        raise RuntimeError("Native process meter did not admit empty bootstrap")
    pool = parallel._Pool(meter)
    try:
        problem = pool.start(1)
        if problem is not None:
            raise RuntimeError(problem)
        record["native_worker_command"] = pool.workers[0].process.args
        table = parallel._files()
        prepared = {"points": {}, "geometry": {}, "face_data": {}, "neumann": set(), "conductivity": 1}
        for message in parallel._inputs(kernel, prepared, (), table):
            pool.workers[0].outbox.put(message)
        slot, data = pool.results.get(timeout=45)
        if slot != 0 or data is None:
            raise RuntimeError("Native bootstrap ended without a ready message")
        head, body = parallel._unpack(data)
        record["worker_reply"] = head
        if head[0] != "ready" or len(body):
            raise AssertionError("Native consumer worker refused: " + repr(head))
        problem = pool.admit(pool.workers[0], head[1], table,
                             (Path(kernel.__file__).resolve().parent, Path(parallel._clone())))
        if problem is not None:
            raise AssertionError("Native ready worker was not admitted: " + problem)
        record["native_admitted"] = True
    finally:
        try:
            record["stop_failures"] = pool.stop(quiet=False, wait=5)
        finally:
            record["meter_report"] = parallel.METER.finish(meter)
            record["worker_exit_codes"] = [worker.process.poll() for worker in pool.workers if worker.process]
            record["native_source_sha256_after"] = sha256(Path(parallel.__file__).read_bytes()).hexdigest()
            record["profile_files"] = {path.name: path.stat().st_size for path in directory.glob("worker-*.prof")}
            with (directory / "receipt.json").open("x", encoding="utf8") as stream:
                json.dump(record, stream, indent=2, sort_keys=True)
    if record["worker_exit_codes"] != [0] or record["stop_failures"]:
        raise AssertionError("Native bootstrap did not stop cleanly")
    if record["native_source_sha256_after"] != R.NATIVE_SHA256:
        raise AssertionError("Native source changed")
    if mode == "prof":
        if len(record["profile_files"]) != 1 or not all(record["profile_files"].values()):
            raise AssertionError("Expected the real native worker profiling output")
    elif record["profile_files"]:
        raise AssertionError("Timing mode unexpectedly enabled profiling")


class ConsumerWorkerRuntime(unittest.TestCase):
    def test_exact_five_layouts_and_two_modes_have_bound_source_subsets(self):
        for layout in ("lw", "ld3", "le3", "lf3", "lh"):
            for mode in ("time", "prof"):
                with self.subTest(layout=layout, mode=mode):
                    pins = R.required_source_pins(layout, mode)
                    self.assertEqual(len(pins), 4 if mode == "prof" else 3)
                    self.assertEqual(str(R.PROFILE_SOURCE) in pins, mode == "prof")
                    self.assertEqual(R._validate_source_pins(layout, mode, pins), pins)

    def test_missing_or_changed_selected_pin_is_refused(self):
        pins = R.required_source_pins("lh", "prof")
        for name in pins:
            for mutation in ("missing", "changed"):
                with self.subTest(name=name, mutation=mutation):
                    changed = pins.copy()
                    if mutation == "missing":
                        changed.pop(name)
                    else:
                        changed[name] = "0" * 64
                    with self.assertRaisesRegex(RuntimeError, "Selected source pin missing or different"):
                        R._validate_source_pins("lh", "prof", changed)

    def test_unselected_mode_layout_and_cross_layout_module_are_refused(self):
        for mode in ("proof", "profile", "", None):
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, "only time/prof"):
                R.enable_and_probe(synthetic_parallel(), mode=mode, source_pins={})
        with self.assertRaisesRegex(RuntimeError, "Unsupported consumer layout"):
            R.required_source_pins("unknown", "time")
        fake = synthetic_parallel()
        fake.__file__ = str(HERE / "helpers/private_heat_functionals_parallel_r1.py")
        with self.assertRaisesRegex(RuntimeError, "exact selected native layout"):
            R.native_layout(fake)

    def test_mode_specific_python_environment_is_enforced_before_probe(self):
        for mode, env in (
            ("time", {"PYTHONHASHSEED": "0", "PYTHONPATH": str(R.WORKERPROF)}),
            ("prof", {"PYTHONHASHSEED": "0"}),
            ("prof", {"PYTHONHASHSEED": "0", "PYTHONPATH": str(HERE)}),
            ("time", {"PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1"}),
        ):
            with self.subTest(mode=mode, env=env), patch.dict(os.environ, env, clear=True), \
                    patch.object(R.sys, "flags", FLAGS), patch.object(R.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "Unexpected Python environment"):
                    R.enable_and_probe(synthetic_parallel(), mode=mode,
                                       source_pins=R.required_source_pins("lf3", mode))
                run.assert_not_called()
                self.assertEqual(dict(os.environ), env)

    def test_original_caller_flags_are_required(self):
        for field, invalid in (("dont_write_bytecode", 0), ("no_user_site", 0), ("safe_path", False),
                               ("hash_randomization", 1), ("ignore_environment", 1), ("isolated", 1)):
            flags = vars(FLAGS) | {field: invalid}
            with self.subTest(field=field), patch.dict(os.environ, {"PYTHONHASHSEED": "0"}, clear=True), \
                    patch.object(R.sys, "flags", SimpleNamespace(**flags)), patch.object(R.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "selected -B -s -P"):
                    R.enable_and_probe(synthetic_parallel(), mode="time",
                                       source_pins=R.required_source_pins("lf3", "time"))
                run.assert_not_called()

    def test_probe_failure_or_runtime_mismatch_restores_environment(self):
        for result, message in (
            (SimpleNamespace(returncode=1, stderr=b"controlled refusal", stdout=b""), "probe failed"),
            (SimpleNamespace(returncode=0, stderr=b"", stdout=pickle.dumps({"flags": ("different",)})),
             "not the caller's"),
        ):
            with self.subTest(message=message), patch.dict(os.environ, {"PYTHONHASHSEED": "0"}, clear=True), \
                    patch.object(R.sys, "flags", FLAGS), patch.object(R.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, message):
                    R.enable_and_probe(synthetic_parallel(), mode="time",
                                       source_pins=R.required_source_pins("lf3", "time"))
                self.assertEqual(dict(os.environ), {"PYTHONHASHSEED": "0"})

    def bootstrap(self, layout, mode):
        ARTIFACTS.mkdir(exist_ok=True)
        directory = Path(tempfile.mkdtemp(dir=ARTIFACTS, prefix=layout + "-" + mode + "-"))
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
        env.pop("HS_PROF_DIR", None)
        env.update(PYTHONHASHSEED="0", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        if mode == "prof":
            env.update(PYTHONPATH=str(R.WORKERPROF), HS_PROF_DIR=str(directory.resolve()))
        command = [str(PYTHON), "-B", "-s", "-P", str(Path(__file__).resolve()),
                   "case", layout, mode, str(directory)]
        with (directory / "stdout.log").open("xb") as stdout, \
                (directory / "stderr.log").open("xb") as stderr:
            result = subprocess.run(command, env=env, cwd=HERE, stdout=stdout, stderr=stderr, timeout=90,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, str(directory))
        receipt = json.loads((directory / "receipt.json").read_bytes())
        self.assertEqual(receipt["scientific_face_tasks_sent"], 0)
        self.assertTrue(receipt["native_admitted"])
        self.assertEqual(receipt["worker_exit_codes"], [0])
        self.assertEqual(receipt["stop_failures"], [])
        self.assertTrue(receipt["runtime"]["full_native_runtime_equal"])
        self.assertEqual(receipt["runtime"]["q22"], "HELD")
        expected_native = str(T / "hs" / layout / "helpers" / (R.NATIVE_NAME + ".py"))
        self.assertEqual(receipt["native_worker_command"], [str(PYTHON), "-B", expected_native, "worker"])
        self.assertEqual(receipt["runtime"]["profiling_pythonpath"], str(R.WORKERPROF) if mode == "prof" else None)

    def test_actual_time_native_bootstrap_new_layout(self):
        self.bootstrap("lw", "time")

    def test_actual_prof_native_bootstrap_retains_worker_profiling(self):
        self.bootstrap("lh", "prof")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "case":
        native_case(sys.argv[2], sys.argv[3], Path(sys.argv[4]))
    else:
        unittest.main(verbosity=2)
