"""Unrun proposal tests: real native worker start/select, with no face tasks."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
PYTHON = T / ".r44-env/Scripts/python.exe"
ARTIFACTS = HERE / "test-artifacts"


def helper():
    spec = importlib.util.spec_from_file_location("worker_flags_repair_proposal", HERE / "worker_flags_repair.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_case(layout, scenario, directory):
    """One fresh selected caller and one native worker, stopped before any face."""
    repair = helper()
    parallel = repair.load_selected(layout)
    import private_heat_functionals_kernel_r5 as kernel
    from atlas_tectonics.resources import WorkBudget
    record = {
        "layout": layout, "scenario": scenario, "scientific_face_tasks_sent": 0,
        "native_parallel_sha256_before": sha256(Path(parallel.__file__).read_bytes()).hexdigest(),
        "caller_runtime": parallel._runtime(),
    }
    if scenario != "original-flags-refusal":
        record["repair"] = repair.enable_and_probe(parallel, mode="proof")
    budget = WorkBudget(6 << 30)
    meter = parallel.METER.open(budget, name="worker-flags-empty-bootstrap")
    if meter is None:
        raise RuntimeError("Native process meter did not admit the bootstrap")
    pool = parallel._Pool(meter)
    try:
        problem = pool.start(1)  # Actual pinned _Pool.start and native launch command.
        if problem is not None:
            raise RuntimeError(problem)
        record["native_worker_command"] = pool.workers[0].process.args
        table = parallel._files()
        if scenario == "source-identity-refusal":
            # Refute weakened source checks without changing any actual file.
            table[str(Path(parallel.__file__).resolve())] = "0" * 64
        prepared = {"points": {}, "geometry": {}, "face_data": {}, "neumann": set(), "conductivity": 1}
        for message in parallel._inputs(kernel, prepared, (), table):
            pool.workers[0].outbox.put(message)
        slot, data = pool.results.get(timeout=45)
        if slot != 0 or data is None:
            raise RuntimeError("Native bootstrap ended without a complete ready/refused message")
        head, body = parallel._unpack(data)
        record["worker_reply"] = head
        if len(body):
            raise RuntimeError("Unexpected native bootstrap body")
        if scenario == "repaired-ready":
            if head[0] != "ready":
                raise AssertionError("Native repaired worker refused: " + repr(head))
            problem = pool.admit(pool.workers[0], head[1], table,
                                 (Path(kernel.__file__).resolve().parent, Path(parallel._clone())))
            if problem is not None:
                raise AssertionError("Native ready worker was not admitted: " + problem)
            record["native_admitted"] = True
        else:
            if head[0] != "refused":
                raise AssertionError("Injected native mismatch was not refused: " + repr(head))
            required = ("The interpreter is not the caller's in: flags"
                        if scenario == "original-flags-refusal" else "Module files that are not the caller's")
            if required not in head[1]:
                raise AssertionError("Native refusal differs: " + repr(head))
            record["native_admitted"] = False
    finally:
        # Native ownership waits for every worker, then releases meter admission.
        try:
            record["stop_failures"] = pool.stop(quiet=False, wait=5)
        finally:
            record["meter_report"] = parallel.METER.finish(meter)
            record["worker_exit_codes"] = [worker.process.poll() for worker in pool.workers if worker.process]
            record["native_parallel_sha256_after"] = sha256(Path(parallel.__file__).read_bytes()).hexdigest()
            with (directory / "receipt.json").open("x", encoding="utf8") as stream:
                json.dump(record, stream, indent=2)
    if any(code is None for code in record["worker_exit_codes"]):
        raise AssertionError("Native worker remains live")
    expected_code = 0 if scenario == "repaired-ready" else 1
    if record["worker_exit_codes"] != [expected_code]:
        raise AssertionError("Unexpected native worker completion: " + repr(record["worker_exit_codes"]))
    if record["native_parallel_sha256_after"] != record["native_parallel_sha256_before"]:
        raise AssertionError("Native source changed")


class WorkerIsolationBootstrap(unittest.TestCase):
    def test_actual_native_worker_ready_and_refusal_both_layouts(self):
        ARTIFACTS.mkdir(exist_ok=True)
        for layout in ("lf3", "lh"):
            for scenario in ("original-flags-refusal", "repaired-ready", "source-identity-refusal"):
                with self.subTest(layout=layout, scenario=scenario):
                    directory = Path(tempfile.mkdtemp(dir=ARTIFACTS, prefix=layout + "-" + scenario + "-"))
                    env = {key: value for key, value in os.environ.items()
                           if not key.upper().startswith("PYTHON")}
                    env.update(PYTHONHASHSEED="0", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
                    command = [str(PYTHON), "-B", "-s", "-P", str(Path(__file__).resolve()),
                               "case", layout, scenario, str(directory)]
                    with (directory / "stdout.log").open("xb") as stdout, \
                            (directory / "stderr.log").open("xb") as stderr:
                        completed = subprocess.run(command, env=env, cwd=HERE, stdout=stdout, stderr=stderr,
                            timeout=75, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    self.assertEqual(completed.returncode, 0, str(directory))
                    result = json.loads((directory / "receipt.json").read_text(encoding="utf8"))
                    self.assertEqual(result["scientific_face_tasks_sent"], 0)
                    self.assertEqual(result["stop_failures"], [])
                    self.assertEqual(result["native_parallel_sha256_before"], helper().NATIVE_SHA256)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "case":
        run_case(sys.argv[2], sys.argv[3], Path(sys.argv[4]))
    else:
        unittest.main(verbosity=2)
