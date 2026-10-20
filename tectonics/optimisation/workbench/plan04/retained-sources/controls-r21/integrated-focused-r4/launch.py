"""One tracked queue admission, then a separate finite selected-control deadline."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from support import P, digest, execution_clean, owner, queue_argv, read_json, require
from support import run_owned, verify_pins, write_new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--admitted", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    require(digest(args.selection) == args.selection_sha256, "Selection bytes changed")
    selected = read_json(args.selection)
    verify_pins(selected["pins"])
    if not args.admitted:
        require(not args.output.exists(), "Output exists")
        args.output.mkdir()
        process = run_owned(args.output / "queue", queue_argv(Path(__file__),
            "--selection", args.selection, "--selection-sha256", args.selection_sha256,
            "--output", args.output, "--admitted"), HERE, 3600)
        queue_exit, tracker = owner.queue_exit((args.output / "queue/stdout.txt").read_text())
        child_path = args.output / "child-result.json"
        child = read_json(child_path) if child_path.is_file() else None
        passed = (execution_clean(process) and process["exit_code"] == queue_exit == 0
                  and child is not None and child["passed"])
        result = {"passed": passed, "process": process, "child": child,
                  "outer_admission_deadline_seconds": 3600, "child_execution_deadline_seconds": 600,
                  "readiness": False, "scientific_capture": False}
        name = "result.json"
    else:
        process = run_owned(args.output / "process", [str(P), "-B", "-s", "-P",
            str(HERE / "driver.py"), str(args.selection), str(args.output / "controls"),
            "--selection-sha256", args.selection_sha256], HERE, 600)
        driver_path = args.output / "controls/result.json"
        driver = read_json(driver_path) if driver_path.is_file() else None
        passed = (execution_clean(process) and process["exit_code"] == 0
                  and driver is not None and driver["status"] == "PASS")
        result = {"passed": passed, "process": process, "driver": str(driver_path),
                  "driver_sha256": digest(driver_path) if driver_path.is_file() else None,
                  "readiness": False, "scientific_capture": False}
        name = "child-result.json"
    verify_pins(selected["pins"])
    write_new(args.output / name, result)
    print(json.dumps({"passed": passed, "result": str(args.output / name)}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
