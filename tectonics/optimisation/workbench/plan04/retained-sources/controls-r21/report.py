"""Fail-closed interpretation; collection exit alone has no attribution value."""
from pathlib import Path
import re


def interpret(process, summary, events, stderr, expected, predicates=()):
    errors = []
    if (process.get("finality") != "COMPLETE" or process.get("log_final") is not True
            or process.get("timed_out") or process.get("cancelled") or process.get("errors")):
        errors.append("process execution/finality incomplete")
    if not isinstance(summary, dict):
        return {"admitted": False, "intended_kill": False,
                "errors": errors + ["missing structured summary"], "matched": []}
    if summary.get("expected") != expected or summary.get("tests_run") != len(expected):
        errors.append("wrong expected set/count")
    started = [event.get("test") for event in events if event.get("kind") == "start"]
    stopped = [event.get("test") for event in events if event.get("kind") == "stop"]
    if started != expected or stopped != expected:
        errors.append("incomplete, repeated, unordered or unexpected test execution")
    terminals = [event for event in events if event.get("kind") == "terminal"]
    if (len(terminals) != 1 or events[-1:] != terminals
            or events[:-1] != summary.get("events")):
        errors.append("missing/inconsistent terminal event")
    failures = [event for event in events if event.get("kind") == "failure"]
    faults = [event for event in events if event.get("kind") == "error"]
    unsupported = [event for event in events if event.get("kind") in
                   ("skip", "expected_failure", "unexpected_success")]
    if faults or summary.get("errors") != 0:
        errors.append("ERROR present (including mixed FAIL+ERROR)")
    if unsupported or any(summary.get(key) != 0 for key in
                          ("skipped", "expected_failures", "unexpected_successes")):
        errors.append("skip or nonstandard unittest outcome")
    if len(failures) != summary.get("failures"):
        errors.append("failure count differs")
    expected_exit = 1 if failures or faults else 0
    if process.get("exit_code") != expected_exit:
        errors.append("abnormal/inconsistent exit")
    if summary.get("successful") is not (not failures and not faults and not unsupported):
        errors.append("structured success disagrees")
    if terminals and terminals[0] != {"kind": "terminal", "tests_run": len(expected),
                                      "failures": len(failures), "errors": len(faults),
                                      "exit_code": expected_exit}:
        errors.append("terminal counts/exit disagree")
    normal = stderr.replace("\r\n", "\n")
    tail = (r"FAILED \(failures=" + str(len(failures)) + r"\)" if failures and not faults
            else "OK" if not failures and not faults else r"FAILED \([^\n]+\)")
    pattern = (r"\n-{70}\nRan " + str(len(expected))
               + r" tests in [0-9]+(?:\.[0-9]+)?s\n\n" + tail + r"\n*\Z")
    if (len(re.findall(r"^Ran \d+ tests? in .*$", normal, re.M)) != 1
            or re.search(pattern, normal) is None):
        errors.append("missing/inconsistent terminal unittest text")
    matched = []
    for index, failure in enumerate(failures):
        for predicate in predicates:
            if not re.search(r"\.test_causal_" + re.escape(predicate["case"]) + "_",
                             failure.get("test", "")):
                continue
            label = predicate.get("subtest")
            if label is not None and failure.get("subtest") != "[" + label + "]":
                continue
            if failure.get("exception") != "AssertionError":
                continue
            if "adapter_line" in predicate:
                hit = any(Path(frame["path"]).name == "test_retained_r20.py"
                          and frame["line"] == predicate["adapter_line"]
                          for frame in failure.get("frames", []))
            else:
                hit = (any(Path(frame["path"]).name == "test_cases_r12.py"
                           and frame["line"] == predicate["retained_line"]
                           for frame in failure.get("frames", []))
                       and any(check.get("expected_status") == predicate["status"]
                               and check.get("needle") == predicate.get("needle")
                               for check in failure.get("checks", [])))
            if hit:
                matched.append({"failure_index": index, "predicate": predicate,
                                "test": failure["test"], "subtest": failure.get("subtest"),
                                "checks": failure.get("checks", [])})
    return {"admitted": not errors, "baseline_clean": not errors and not failures,
            "intended_kill": not errors and bool(matched), "errors": errors,
            "matched": matched, "failure_count": len(failures), "error_count": len(faults),
            "other_failure_indices": sorted(set(range(len(failures))) -
                                            {match["failure_index"] for match in matched})}
