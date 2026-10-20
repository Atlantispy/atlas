"""Pinned timing/profiling worker isolation; no scientific launch entry point.

The original native worker command remains ``python -B native.py worker``.
Only its inherited no-user-site/safe-path environment is added. The original
proof helper and the native parallel module are never modified.
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
    "lw": "62a36c069e133f7982f8bc452de86e31671179cbe17636fddd78c12321ea85e1",
    "ld3": "29af03ca47c93e23e7cb2cb53c88a328b2102ea65e3859c9349aa2216edfa53d",
    "le3": "3c298669325f35891927e4c83d3c43f7cd157c03bda20ebfceb1284d42c55067",
    "lf3": "e5cef40c1b15a263a74d894252321a5af969ce35b37b9dfcf31aa3b94fd123c6",
    "lh": "acd34ca42dc6464f4654e518d322d1ee03e1900b8159e0012fc3e6a2b27265d8",
}
WORKERPROF = (T / "hs/workerprof").resolve()
PROFILE_SOURCE = WORKERPROF / "sitecustomize.py"
PROFILE_SHA256 = "8103fc4f99b1755ff32d3185bff8f29720c95de69aed32b89ce06f8c4bc56a0a"
ISOLATION_ENV = {"PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1"}
MODES = ("time", "prof")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def required_source_pins(layout_name, mode):
    """Exact manifest subset, including the profiling startup hook when used."""
    require(mode in MODES, "Consumer worker runtime supports only time/prof")
    require(layout_name in CONTROL_PINS, "Unsupported consumer layout")
    layout = (T / "hs" / layout_name).resolve()
    pins = {
        str(Path(__file__).resolve()): digest(__file__),
        str(layout / "helpers" / (NATIVE_NAME + ".py")): NATIVE_SHA256,
        str(layout / "control.json"): CONTROL_PINS[layout_name],
    }
    if mode == "prof":
        pins[str(PROFILE_SOURCE)] = PROFILE_SHA256
    return pins


def _validate_source_pins(layout_name, mode, source_pins):
    require(isinstance(source_pins, dict), "Explicit selected manifest source pins required")
    expected = required_source_pins(layout_name, mode)
    for path, pin in expected.items():
        require(source_pins.get(path) == pin, "Selected source pin missing or different: " + path)
        require(Path(path).is_file() and digest(path) == pin, "Selected source bytes differ: " + path)
    return expected


def native_layout(parallel):
    source = Path(parallel.__file__).resolve()
    layout = source.parent.parent
    require(layout.name in CONTROL_PINS and layout == (T / "hs" / layout.name).resolve(),
            "Consumer worker runtime requires one exact selected native layout")
    require(source == layout / "helpers" / (NATIVE_NAME + ".py"),
            "Parallel module is outside the selected native helper path")
    require(digest(source) == NATIVE_SHA256, "Native parallel source differs")
    require(digest(layout / "control.json") == CONTROL_PINS[layout.name], "Native control source differs")
    return layout


def load_selected(layout_name, *, mode, source_pins):
    """Fresh nonscientific probe process; validate before importing native code."""
    _validate_source_pins(layout_name, mode, source_pins)
    require(NATIVE_NAME not in sys.modules, "Runtime probe requires a fresh native selection")
    layout = (T / "hs" / layout_name).resolve()
    sys.path[:0] = json.loads((layout / "control.json").read_bytes())["paths"]
    parallel = importlib.import_module(NATIVE_NAME)
    require(native_layout(parallel) == layout, "Loaded native layout differs")
    return parallel


def _python_environment():
    return {key.upper(): value for key, value in os.environ.items()
            if key.upper().startswith("PYTHON")}


def enable_and_probe(parallel, *, mode, source_pins):
    """Inherit caller isolation and compare the native complete runtime record.

    The caller must already use -B -s -P with seed zero. Time has no PYTHONPATH;
    prof retains only the exact, pinned workerprof startup directory. A failed
    probe restores the original environment; no fallback is authorised here.
    """
    require(mode in MODES, "Consumer worker runtime supports only time/prof")
    layout = native_layout(parallel)
    selected = _validate_source_pins(layout.name, mode, source_pins)
    flags = sys.flags
    require(flags.dont_write_bytecode and flags.no_user_site and flags.safe_path
            and not flags.hash_randomization and not flags.ignore_environment and not flags.isolated,
            "Caller must use the selected -B -s -P, seed-zero interpreter contract")
    wanted = {"PYTHONHASHSEED": "0"}
    if mode == "prof":
        wanted["PYTHONPATH"] = str(WORKERPROF)
    require(_python_environment() == wanted, "Unexpected Python environment for " + mode)
    before = dict(os.environ)
    try:
        os.environ.update(ISOLATION_ENV)
        caller_runtime = parallel._runtime()
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "runtime", mode, layout.name]
        completed = subprocess.run(
            command, input=json.dumps(selected, sort_keys=True).encode("utf8"),
            env=dict(os.environ, OPENBLAS_NUM_THREADS="1"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        require(completed.returncode == 0,
                "Native worker-style runtime probe failed: "
                + completed.stderr.decode("utf8", "replace")[-2000:])
        # Produced only by this hash-bound local helper in the pinned interpreter.
        worker_runtime = pickle.loads(completed.stdout)
        require(isinstance(worker_runtime, dict), "Native runtime probe returned no record")
        wrong = sorted(key for key in set(caller_runtime) | set(worker_runtime)
                       if caller_runtime.get(key) != worker_runtime.get(key))
        require(not wrong, "Worker-style runtime is not the caller's in: " + ", ".join(wrong))
        _validate_source_pins(layout.name, mode, source_pins)
        require(_python_environment() == wanted | ISOLATION_ENV,
                "Python environment changed during native runtime probe")
        return {
            "schema": "plan05.consumer-worker-runtime.r1", "mode": mode, "layout": layout.name,
            "source_pins": selected, "helper_path": str(Path(__file__).resolve()),
            "helper_sha256": selected[str(Path(__file__).resolve())],
            "native_parallel_path": str(Path(parallel.__file__).resolve()),
            "native_parallel_sha256": NATIVE_SHA256,
            "native_control_path": str(layout / "control.json"),
            "native_control_sha256": CONTROL_PINS[layout.name],
            "caller_command_flags": ["-B", "-s", "-P"],
            "worker_command_flags": ["-B"],
            "inherited_worker_environment": dict(ISOLATION_ENV),
            "python_environment_before": wanted,
            "python_environment_after": _python_environment(),
            "python_variables_after": sorted(key for key in os.environ if key.upper().startswith("PYTHON")),
            "profiling_pythonpath": str(WORKERPROF) if mode == "prof" else None,
            "caller_runtime": caller_runtime, "worker_probe_runtime": worker_runtime,
            "full_native_runtime_equal": True, "native_source_changed": False,
            "scientific_work_dispatched": False, "q22": "HELD",
        }
    except BaseException:
        for key in ISOLATION_ENV:
            if key in before:
                os.environ[key] = before[key]
            else:
                os.environ.pop(key, None)
        raise


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "runtime":
        raise SystemExit("Only the nonscientific consumer runtime probe is supported")
    pins = json.loads(sys.stdin.buffer.read())
    selected = load_selected(sys.argv[3], mode=sys.argv[2], source_pins=pins)
    sys.stdout.buffer.write(pickle.dumps(selected._runtime(), protocol=pickle.HIGHEST_PROTOCOL))
