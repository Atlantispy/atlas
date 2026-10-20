"""Additive selected-route proposal: inherit isolation into unchanged workers.

This module has no scientific launch entry point. ``runtime`` is a bounded,
read-only interpreter identity probe using the pinned native _runtime API.
"""
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys


T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
NATIVE_NAME = "private_heat_functionals_parallel_r1"
NATIVE_SHA256 = "c23254296e32c72b35381b5e9326a5e7f10e868f5e5739aa64247518fe4fec05"
CONTROL_PINS = {
    "lf3": "e5cef40c1b15a263a74d894252321a5af969ce35b37b9dfcf31aa3b94fd123c6",
    "lh": "acd34ca42dc6464f4654e518d322d1ee03e1900b8159e0012fc3e6a2b27265d8",
}
ISOLATION_ENV = {"PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def native_layout(parallel):
    source = Path(parallel.__file__).resolve()
    layout = source.parent.parent
    require(layout.name in CONTROL_PINS and layout == (T / "hs" / layout.name).resolve(),
            "Worker flags repair requires one selected native layout")
    require(source == layout / "helpers" / (NATIVE_NAME + ".py"),
            "Parallel module is outside the selected helper path")
    require(sha256(source.read_bytes()).hexdigest() == NATIVE_SHA256,
            "Native parallel source differs from the reviewed source")
    require(sha256((layout / "control.json").read_bytes()).hexdigest() == CONTROL_PINS[layout.name],
            "Selected control source differs")
    return layout


def load_selected(layout_name):
    """For a fresh bootstrap process; imports only the selected native API."""
    require(layout_name in CONTROL_PINS, "Unsupported layout")
    layout = (T / "hs" / layout_name).resolve()
    raw = (layout / "control.json").read_bytes()
    require(sha256(raw).hexdigest() == CONTROL_PINS[layout_name], "Selected control source differs")
    require(NATIVE_NAME not in sys.modules, "Bootstrap requires a fresh native module selection")
    sys.path[:0] = json.loads(raw)["paths"]
    parallel = importlib.import_module(NATIVE_NAME)
    require(native_layout(parallel) == layout, "Loaded parallel module differs")
    return parallel


def enable_and_probe(parallel, *, mode):
    """Called after the existing selected writer's original environment fence.

    -s/-P remain on the caller command. Their environment equivalents give the
    unchanged native command (python -B native.py worker) the same sys.flags.
    No native module function, source, command or runtime identity is replaced.
    """
    require(mode == "proof", "This repair proposal supports only the selected proof route")
    layout = native_layout(parallel)
    flags = sys.flags
    require(flags.dont_write_bytecode and flags.no_user_site and flags.safe_path
            and not flags.hash_randomization and not flags.ignore_environment and not flags.isolated,
            "Caller must retain the selected -B -s -P, seed-zero interpreter contract")
    present = {key.upper(): value for key, value in os.environ.items()
               if key.upper().startswith("PYTHON")}
    require(present == {"PYTHONHASHSEED": "0"}, "Unexpected Python environment before isolation inheritance")
    # Keep the original launch flags. These values affect future interpreters,
    # including the unchanged native _Pool.start, rather than this interpreter.
    os.environ.update(ISOLATION_ENV)
    caller_runtime = parallel._runtime()
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "runtime", layout.name]
    completed = subprocess.run(command, env=dict(os.environ, OPENBLAS_NUM_THREADS="1"),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    require(completed.returncode == 0,
            "Native worker-style runtime probe failed: " + completed.stderr.decode("utf8", "replace")[-2000:])
    # Bytes come only from the pinned local interpreter and this reviewed local
    # helper. The native worker protocol also serialises these trusted values.
    worker_runtime = pickle.loads(completed.stdout)
    wrong = sorted(key for key in set(caller_runtime) | set(worker_runtime)
                   if caller_runtime.get(key) != worker_runtime.get(key))
    require(not wrong, "Worker-style runtime is not the caller's in: " + ", ".join(wrong))
    return {
        "schema": "atlas.private.worker-isolation-repair.r1",
        "helper_path": str(Path(__file__).resolve()),
        "helper_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "native_parallel_path": str(Path(parallel.__file__).resolve()),
        "native_parallel_sha256": NATIVE_SHA256,
        "worker_command_flags": ["-B"],
        "inherited_worker_environment": dict(ISOLATION_ENV),
        "python_variables_after": sorted(key for key in os.environ if key.upper().startswith("PYTHON")),
        "caller_runtime": caller_runtime,
        "worker_probe_runtime": worker_runtime,
        "full_native_runtime_equal": True,
        "native_source_changed": False,
        "scientific_work_dispatched": False,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "runtime":
        raise SystemExit("Only the nonscientific runtime identity probe is supported")
    selected = load_selected(sys.argv[2])
    sys.stdout.buffer.write(pickle.dumps(selected._runtime(), protocol=pickle.HIGHEST_PROTOCOL))
