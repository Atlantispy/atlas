"""Run unchanged causal test bodies with durable structured unittest events."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import traceback
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("adapter", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    # This runner is supplied by the pinned parent; adapter bytes are pinned by
    # the generated adapter and parent manifest before and after execution.
    spec = importlib.util.spec_from_file_location("mutation_adapter", args.adapter)
    adapter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = adapter
    spec.loader.exec_module(adapter)
    events = []
    event_path = args.evidence.with_suffix(".events.jsonl")
    with event_path.open("x", encoding="utf-8", newline="\n") as stream:
        def emit(kind, test=None, **data):
            row = {"kind": kind, **data}
            if test is not None:
                row["test"] = test.id()
            events.append(row)
            stream.write(json.dumps(row, allow_nan=False) + "\n")
            stream.flush()

        def details(err):
            frames = []
            checks = []
            cursor = err[2]
            while cursor:
                frame = cursor.tb_frame
                frames.append({"path": frame.f_code.co_filename,
                               "function": frame.f_code.co_name, "line": cursor.tb_lineno})
                if frame.f_code.co_name == "check" and "verdict" in frame.f_locals:
                    values = frame.f_locals
                    checks.append({"expected_status": values.get("status"),
                                   "needle": values.get("needle"), "where": values.get("where"),
                                   "actual_status": values["verdict"].get("status")})
                cursor = cursor.tb_next
            return {"exception": err[0].__name__, "message": str(err[1]),
                    "frames": frames, "checks": checks,
                    "traceback": "".join(traceback.format_exception(*err))}

        class Recorded(unittest.TextTestResult):
            def startTest(self, test):
                super().startTest(test)
                emit("start", test)

            def stopTest(self, test):
                emit("stop", test)
                super().stopTest(test)

            def addSuccess(self, test):
                emit("success", test)
                super().addSuccess(test)

            def addFailure(self, test, err):
                emit("failure", test, **details(err))
                super().addFailure(test, err)

            def addError(self, test, err):
                emit("error", test, **details(err))
                super().addError(test, err)

            def addSubTest(self, test, subtest, err):
                kind = "subtest_success" if err is None else (
                    "failure" if issubclass(err[0], test.failureException) else "error")
                emit(kind, test, subtest=subtest._subDescription(),
                     **({} if err is None else details(err)))
                super().addSubTest(test, subtest, err)

            def addSkip(self, test, reason):
                emit("skip", test, reason=reason)
                super().addSkip(test, reason)

            def addExpectedFailure(self, test, err):
                emit("expected_failure", test, **details(err))
                super().addExpectedFailure(test, err)

            def addUnexpectedSuccess(self, test):
                emit("unexpected_success", test)
                super().addUnexpectedSuccess(test)

        adapter.verify_sources()
        expected = ["mutation_adapter.Causal." + name for name in adapter.CAUSAL_NAMES]
        emit("begin", expected=expected)
        result = unittest.TextTestRunner(verbosity=2, resultclass=Recorded).run(
            adapter.selected_suite("causal"))
        adapter.verify_sources()
        if adapter.C.REPAIRS_COMPLETE is not False:
            raise AssertionError("Readiness guard changed")
        summary = {"tests_run": result.testsRun, "failures": len(result.failures),
                   "errors": len(result.errors), "skipped": len(result.skipped),
                   "expected_failures": len(result.expectedFailures),
                   "unexpected_successes": len(result.unexpectedSuccesses),
                   "successful": result.wasSuccessful(), "expected": expected,
                   "events": events, "observations": adapter.OBSERVATIONS}
        with args.evidence.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(summary, output, indent=1, allow_nan=False)
            output.write("\n")
        emit("terminal", tests_run=result.testsRun, failures=len(result.failures),
             errors=len(result.errors), exit_code=0 if result.wasSuccessful() else 1)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
