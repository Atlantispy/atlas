"""One selected group/attempt, explicit new outputs and frozen source checks."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from support import BASE_PINS_SHA, OWNER, P, T, digest, execution_clean, owner, queue_argv, read_json
from support import require, run_owned, verify_pins, write_new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=("focused", "all", "retained", "causal"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--admitted", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    pins = read_json(ROOT / "SOURCE-PINS.json")["pins"]
    verify_pins(pins)
    require(digest(OWNER / "INPUT-PINS.json") == BASE_PINS_SHA, "Original input manifest changed")
    frozen = read_json(OWNER / "INPUT-PINS.json")["source_pins"]
    frozen[str(T / "q/runq.py")] = "0bcffc6655e727adf46f0796f1a77916a64046c93244d2ed7f000b84d648eb5f"
    verify_pins(frozen)
    if not args.admitted:
        require(not args.output.exists(), "Evidence output exists")
        args.output.mkdir()
        process = run_owned(args.output / "queue", queue_argv(Path(__file__),
                            "--group", args.group, "--output", args.output, "--admitted"), ROOT, 3600)
        queue_exit, tracker = owner.queue_exit((args.output / "queue/stdout.txt").read_text())
        child_path = args.output / "child-result.json"
        child = read_json(child_path) if child_path.is_file() else None
        passed = (execution_clean(process) and process["exit_code"] == queue_exit == 0
                  and child is not None and child["passed"])
        verify_pins(pins)
        verify_pins(frozen)
        write_new(args.output / "result.json", {"passed": passed, "group": args.group,
                  "queue_process": process, "child": child, "selected_input_pins": frozen,
                  "queue_change_reason": "Plan6 fail-closed AccessDenied repair explicitly selected",
                  "admission_and_outer_deadline_seconds": 3600, "child_execution_deadline_seconds": 180,
                  "scientific_capture": False})
        print(json.dumps({"passed": passed, "group": args.group,
                          "result": str(args.output / "result.json")}), flush=True)
        return 0 if passed else 1
    evidence = args.output / "adapter-evidence.json"
    process = run_owned(args.output / "process", [str(P), "-B", "-s", "-P",
                        str(ROOT / "test_retained_r20.py"), "--group", args.group,
                        "--evidence", str(evidence)], ROOT, 180)
    report = read_json(evidence) if evidence.is_file() else None
    contract = read_json(ROOT / "EXPECTED.json")
    stderr = (args.output / "process/stderr.txt").read_text().replace("\r\n", "\n")
    verify_pins(pins)
    verify_pins(frozen)
    passed = (execution_clean(process) and process["exit_code"] == 0
              and report is not None and report.get("status") == "PASS"
              and report.get("failures") == report.get("errors") == report.get("skipped") == 0
              and report.get("tests_run") == {"focused": 6, "causal": 18, "retained": 47, "all": 71}[args.group])
    verification_errors = []
    try:
        require(report is not None, "No adapter evidence")
        require(report.get("sources") == contract["adapter_sources"], "Adapter dependency pins")
        for key in ("retained_names", "focused_names", "causal_names"):
            require(report.get(key) == contract[key], "Adapter exact case set: " + key)
        count = {"focused": 6, "causal": 18, "retained": 47, "all": 71}[args.group]
        require(len(re.findall(r"^Ran \d+ tests? in .*", stderr, re.M)) == 1, "Missing/duplicate terminal")
        require(re.search(r"\n-{70}\nRan %d tests in [0-9]+(?:\.[0-9]+)?s\n\nOK\n*\Z" % count,
                          stderr) is not None, "Non-clean/incomplete terminal")
        if args.group == "all":
            owner.verify_adapter(report, stderr, contract)
    except ValueError as exc:
        verification_errors.append(str(exc))
    passed = passed and not verification_errors
    summary = {"passed": passed, "group": args.group, "process": process,
               "source_pins": pins, "explicit_selected_input_pins_unchanged": True,
               "adapter_evidence": str(evidence), "verification_errors": verification_errors,
               "scientific_capture": False}
    write_new(args.output / "child-result.json", summary)
    print(json.dumps({"passed": passed, "group": args.group, "tests": report.get("tests_run") if report else None,
                      "result": str(args.output / "result.json")}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
