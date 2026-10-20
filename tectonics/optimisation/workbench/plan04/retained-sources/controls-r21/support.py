"""Bounded synthetic control support; no scientific execution or readiness change."""
import hashlib
import os
from pathlib import Path
import sys
import time
import traceback
from types import ModuleType

ROOT = Path(__file__).resolve().parent
W = Path("C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace")
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
C = W / "work/plan04/causal-r20"
OWNER = C / "owner-run-r1"
P = T / ".r44-env/Scripts/python.exe"
OWNER_SHA = "3b6b15fa1f931e0732fa9a9abef88d3f2e8ef3545757ee0ae3550b0e9076f38e"
BASE_PINS_SHA = "3fddd4b92300f6b36e2e00b7afc7ab6e5d7917b3a3eee90005da34b1844841d6"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_source(path, name, expected):
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, "Source changed: " + str(path))
    module = ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


owner = load_source(OWNER / "launch_r20_owner_r1.py", "frozen_owner_support", OWNER_SHA)
read_json, write_new, verify_pins = owner.read_json, owner.write_new, owner.verify_pins


def inputs():
    require(digest(OWNER / "INPUT-PINS.json") == BASE_PINS_SHA, "Frozen input manifest changed")
    pins = read_json(OWNER / "INPUT-PINS.json")["source_pins"]
    verify_pins(pins)
    return pins


def runtime():
    require(os.name == "nt" and sys.implementation.name == "cpython"
            and sys.version_info[:2] == (3, 12) and sys.maxsize == (1 << 63) - 1,
            "Requires selected Windows 64-bit CPython 3.12")
    require(Path(sys.executable).resolve() == P.resolve() and not sys.flags.optimize,
            "Wrong interpreter or disabled assertions")


def run_owned(folder, argv, cwd, seconds):
    """Retain both streams from launch, even on timeout or abnormal exit.

    Supervision and Job ownership are the exact unchanged reviewed implementation.
    A nested owned Job retains every inner test's independent finality evidence.
    """
    folder = Path(folder)
    folder.mkdir(exist_ok=False)
    (folder / "temp").mkdir()
    env = owner.child_env()
    env["TEMP"] = env["TMP"] = str(folder / "temp")
    row = {"argv": list(argv), "cwd": str(cwd), "deadline_seconds": seconds,
           "cleanup_seconds": 10, "log_final": False}
    result = {"finality": "UNRESOLVED", "exit_code": None, "errors": [],
              "timed_out": False, "cancelled": False, "process_created": False}
    job = None
    start = time.monotonic()
    paths = [folder / "stdout.txt", folder / "stderr.txt"]
    with paths[0].open("xb") as stdout, paths[1].open("xb") as stderr:
        try:
            job = owner.load_backend()()
            job.start(argv, cwd, env, stdout, stderr)
            result = owner.supervise(job, start + seconds)
        except BaseException as failure:
            result["errors"].append(traceback.format_exc())
            result["cancelled"] = isinstance(failure, (KeyboardInterrupt, SystemExit))
            if job is not None:
                result["process_created"] = bool(job.pi.process)
                owner.recover_finality(job, result)
        finally:
            if job is not None:
                row["ownership"] = dict(job.identity)
                try:
                    job.close()
                except BaseException:
                    result["errors"].append(traceback.format_exc())
    row.update(result)
    row["elapsed_seconds"] = time.monotonic() - start
    row["log_final"] = result["finality"] == "COMPLETE"
    row["logs"] = {str(path): {"sha256": digest(path), "bytes": path.stat().st_size,
                             "final": row["log_final"]} for path in paths}
    write_new(folder / "process.json", row)
    return row


def queue_argv(entry, *args):
    return [str(P), "-B", "-I", str(T / "q/runq.py"), "small", "--cores", "1",
            "--gib", "0.5", "--", str(P), "-B", "-s", "-P", str(entry), *map(str, args)]


def execution_clean(row):
    return (row.get("finality") == "COMPLETE" and row.get("log_final") is True
            and not row.get("errors") and not row.get("timed_out")
            and not row.get("cancelled"))
