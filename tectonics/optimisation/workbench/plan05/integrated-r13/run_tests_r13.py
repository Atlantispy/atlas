"""Focused tests only; a structured result preserves failures and exact case coverage."""
import argparse
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("Refusing to overwrite prior evidence")
    sys.path.insert(0, str(HERE))
    suite = unittest.TestSuite()
    # Launcher controls have their separate evidence; affected controls are
    # rerun separately when a launcher boundary changes.
    for name in ("test_ownership_r13", "test_verifier_r13", "test_writer_verifier_r13"):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    expected = list(flatten(suite))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    record = dict(schema="plan05-focused-tests-r13.v1", expected=expected,
                  run=result.testsRun, failures=[(test.id(), text) for test, text in result.failures],
                  errors=[(test.id(), text) for test, text in result.errors],
                  skipped=[(test.id(), why) for test, why in result.skipped])
    record["passed"] = (result.wasSuccessful() and not result.skipped and
                        result.testsRun == len(expected) and result.testsRun > 0)
    with args.out.open("x", encoding="utf8") as stream:
        json.dump(record, stream, indent=2)
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
