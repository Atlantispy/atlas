"""Bounded known-fault controls for evidence reporting, not a repeated OS audit."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report import interpret
from support import P, ROOT, owner, require, run_owned, write_new

EXPECTED = ["mutation_adapter.Causal.test_causal_01_example",
            "mutation_adapter.Causal.test_causal_02_example"]
PRED = {"case": "01", "status": "FAIL", "needle": "specific defect",
        "retained_line": 79, "subtest": "fault"}


def fixture(fail=True):
    process = {"finality": "COMPLETE", "log_final": True, "timed_out": False,
               "cancelled": False, "errors": [], "exit_code": int(fail)}
    failure = {"kind": "failure", "test": EXPECTED[0], "subtest": "[fault]",
               "exception": "AssertionError", "frames": [{"path": "test_cases_r12.py", "line": 79}],
               "checks": [{"expected_status": "FAIL", "needle": "specific defect", "actual_status": "PASS"}]}
    events = [{"kind": "begin", "expected": EXPECTED}, {"kind": "start", "test": EXPECTED[0]},
              failure if fail else {"kind": "success", "test": EXPECTED[0]},
              {"kind": "stop", "test": EXPECTED[0]}, {"kind": "start", "test": EXPECTED[1]},
              {"kind": "success", "test": EXPECTED[1]}, {"kind": "stop", "test": EXPECTED[1]}]
    summary = {"expected": EXPECTED, "tests_run": 2, "failures": int(fail), "errors": 0,
               "skipped": 0, "expected_failures": 0, "unexpected_successes": 0,
               "successful": not fail, "events": copy.deepcopy(events)}
    events.append({"kind": "terminal", "tests_run": 2, "failures": int(fail),
                   "errors": 0, "exit_code": int(fail)})
    stderr = "\n" + "-" * 70 + "\nRan 2 tests in 0.001s\n\n" + (
        "FAILED (failures=1)\n" if fail else "OK\n")
    return process, summary, events, stderr


class Reporting(unittest.TestCase):
    def judge(self, values, predicates=(PRED,)):
        return interpret(*values, EXPECTED, predicates)

    def test_clean_baseline_and_intended_failure(self):
        self.assertTrue(self.judge(fixture(False))["baseline_clean"])
        self.assertTrue(self.judge(fixture())["intended_kill"])

    def test_wrong_predicate_never_counts(self):
        values = fixture()
        values[2][2]["checks"][0]["needle"] = "unrelated assertion"
        values[1]["events"] = copy.deepcopy(values[2][:-1])
        result = self.judge(values)
        self.assertTrue(result["admitted"])
        self.assertFalse(result["intended_kill"])

    def test_mixed_failure_error_same_test(self):
        values = fixture()
        values[2].insert(3, {"kind": "error", "test": EXPECTED[0], "exception": "KeyError"})
        values[1]["events"] = copy.deepcopy(values[2][:-1])
        values[1]["errors"] = 1
        values[2][-1]["errors"] = 1
        self.assertFalse(self.judge(values)["intended_kill"])
        self.assertIn("ERROR present (including mixed FAIL+ERROR)", self.judge(values)["errors"])

    def test_error_only(self):
        values = fixture()
        values[2][2]["kind"] = "error"
        values[1].update(failures=0, errors=1, events=copy.deepcopy(values[2][:-1]))
        values[2][-1].update(failures=0, errors=1)
        self.assertFalse(self.judge(values)["intended_kill"])

    def test_abnormal_exit_after_assertion(self):
        values = fixture()
        values[0]["exit_code"] = 9
        self.assertFalse(self.judge(values)["intended_kill"])

    def test_incomplete_or_duplicate_execution(self):
        for index in (1, 3, 4, 6):
            values = fixture()
            values[2].pop(index)
            values[1]["events"] = copy.deepcopy(values[2][:-1])
            self.assertFalse(self.judge(values)["intended_kill"])
        values = fixture()
        values[2].insert(1, values[2][1])
        values[1]["events"] = copy.deepcopy(values[2][:-1])
        self.assertFalse(self.judge(values)["intended_kill"])

    def test_missing_terminal_event_and_text(self):
        values = fixture()
        values[2].pop()
        self.assertFalse(self.judge(values)["intended_kill"])
        values = list(fixture())
        values[3] = values[3].replace("FAILED (failures=1)\n", "")
        self.assertFalse(self.judge(values)["intended_kill"])

    def test_terminal_count_mismatch(self):
        values = fixture()
        values[2][-1]["tests_run"] = 1
        self.assertFalse(self.judge(values)["intended_kill"])

    def test_finality_timeout_cancel_and_query_errors(self):
        for patch in ({"finality": "UNRESOLVED"}, {"timed_out": True},
                      {"cancelled": True}, {"errors": ["query error"]}, {"log_final": False}):
            values = fixture()
            values[0].update(patch)
            self.assertFalse(self.judge(values)["intended_kill"])
        self.assertFalse(owner.completed({"job": {"active": 1}, "exit_code": 0}))
        self.assertFalse(owner.completed({"job": {"active": 0}, "exit_code": None}))
        with self.assertRaises(ValueError):
            owner.completed({"job": {}, "exit_code": 0})

    def test_skip_and_expected_failure_refuse_baseline(self):
        for key in ("skipped", "expected_failures", "unexpected_successes"):
            values = fixture(False)
            values[1][key] = 1
            self.assertFalse(self.judge(values)["baseline_clean"])

    def test_changed_structured_summary(self):
        values = fixture()
        values[1]["events"][2]["checks"][0]["needle"] = "changed"
        self.assertFalse(self.judge(values)["intended_kill"])


def main():
    output = Path(sys.argv[1])
    require(not output.exists(), "Reporting evidence already exists")
    output.mkdir()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Reporting))
    # Exercise this wrapper's stdout/stderr retention on actual timeout. It
    # reuses unchanged Job containment; there is no second OS containment audit.
    timeout = run_owned(output / "timeout", [str(P), "-B", "-s", "-P", "-c",
        "import sys,time;print('stdout-before-timeout',flush=True);"
        "print('stderr-before-timeout',file=sys.stderr,flush=True);time.sleep(30)"], ROOT, 1.5)
    retained = ("stdout-before-timeout" in (output / "timeout/stdout.txt").read_text()
                and "stderr-before-timeout" in (output / "timeout/stderr.txt").read_text())
    timeout_ok = timeout["timed_out"] and timeout["finality"] == "COMPLETE" and retained
    abnormal = run_owned(output / "abnormal", [str(P), "-B", "-s", "-P", "-c",
        "import sys;print('AssertionError: planted',file=sys.stderr,flush=True);sys.exit(9)"], ROOT, 10)
    abnormal_ok = abnormal["exit_code"] == 9 and abnormal["finality"] == "COMPLETE"
    payload = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "timeout_streams_and_finality": bool(timeout_ok), "abnormal_exit_retained": abnormal_ok,
               "passed": result.wasSuccessful() and timeout_ok and abnormal_ok}
    write_new(output / "result.json", payload)
    print(json.dumps(payload), flush=True)
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
