"""Reuse the qualified 17 bootstrap controls for the two-constant successor.

Synthetic fixtures only: no native commands, Atlas imports or production output
writes. Root owns source construction, exact entry qualification and run clearance.
"""
import argparse
from hashlib import sha256
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
BASE = HERE.parent / "native-entry-r1"
BASE_BOOTSTRAP = BASE / "bootstrap_native.py"
BASE_SHA = "f5009a2d9907a4835197714a86587ea4390a7d75a7eb830ca62311c594cc71f5"
TEST_SOURCE = BASE / "test_bootstrap_native.py"
TEST_SHA = "43f4148e0e346c22e032229d73ac5875b8ada2c18e160fafb42f12b47fee2101"
CANDIDATE = WORK / "plans10-12-integration-r1/bootstrap_native.py"
TARGET = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/ac/p1012-r1")
EXPECTED_METHODS = 17


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked(path, pin):
    require(type(pin) is str and len(pin) == 64 and
            all(char in "0123456789abcdef" for char in pin), "complete lowercase source pin required")
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == pin, "source pin differs: " + str(path))
    return raw


def replace_once(raw, old, new):
    require(raw.count(old) == 1, "exact single source anchor required: " + repr(old))
    return raw.replace(old, new, 1)


class NoAtlas(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "atlas_tectonics" or fullname.startswith("atlas_tectonics."):
            raise ImportError("actual Atlas imports forbidden in synthetic bootstrap controls")
        return None


def atlas_loaded():
    return any(name == "atlas_tectonics" or name.startswith("atlas_tectonics.") for name in sys.modules)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-sha256", required=True)
    parser.add_argument("--helper-count", required=True, type=int)
    args = parser.parse_args(argv)
    require(args.helper_count > 0, "actual positive successor helper count required")
    counts = (239, args.helper_count)
    base = checked(BASE_BOOTSTRAP, BASE_SHA)
    tests = checked(TEST_SOURCE, TEST_SHA)
    candidate = checked(CANDIDATE, args.bootstrap_sha256)
    expected = replace_once(base, b'REAL_ROOT = T / "ac/p11-out/composed-r13"',
                            b'REAL_ROOT = T / "ac/p1012-r1"')
    expected = replace_once(expected, b"REAL_COUNTS = (239, 389)",
                            ("REAL_COUNTS = " + repr(counts)).encode("ascii"))
    require(candidate == expected, "successor must differ only in REAL_ROOT and REAL_COUNTS")

    # Replace only the pinned test module's bootstrap-loading preamble and its
    # one literal count assertion. Every original test method otherwise survives.
    preamble = b'''HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("_native_entry_controls", HERE / "bootstrap_native.py")
B = importlib.util.module_from_spec(_SPEC)
_RAW = (HERE / 'bootstrap_native.py').read_bytes()
assert sha256(_RAW).hexdigest() == 'f5009a2d9907a4835197714a86587ea4390a7d75a7eb830ca62311c594cc71f5'
exec(compile(_RAW, str(HERE / 'bootstrap_native.py'), 'exec', dont_inherit=True), B.__dict__)
'''
    adapted = replace_once(tests, preamble, b"HERE = FIXTURE_ROOT\nB = SUCCESSOR\n")
    adapted = replace_once(adapted,
        b'{"expected_root": B.REAL_ROOT, "expected_counts": (239, 389)}',
        b'{"expected_root": EXPECTED_ROOT, "expected_counts": EXPECTED_COUNTS}')
    require(not atlas_loaded(), "preloaded Atlas modules refused in synthetic controls")
    guard = NoAtlas()
    sys.meta_path.insert(0, guard)
    try:
        spec = importlib.util.spec_from_file_location("_combined_bootstrap_under_test", CANDIDATE)
        successor = importlib.util.module_from_spec(spec)
        exec(compile(candidate, str(CANDIDATE), "exec", dont_inherit=True), successor.__dict__)
        require(successor.REAL_ROOT == TARGET and successor.REAL_COUNTS == counts,
                "executed successor constants differ")
        # All fixture paths remain inside this adapter's owned directory. The
        # production root/profile/store paths are never created or opened.
        with tempfile.TemporaryDirectory(prefix="successor-bootstrap-", dir=HERE) as temporary:
            namespace = {"__name__": "_combined_bootstrap_controls", "__file__": str(TEST_SOURCE),
                         "FIXTURE_ROOT": Path(temporary).resolve(), "SUCCESSOR": successor,
                         "EXPECTED_ROOT": TARGET, "EXPECTED_COUNTS": counts}
            exec(compile(adapted, str(TEST_SOURCE), "exec", dont_inherit=True), namespace)
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(namespace["BootstrapControls"])
            require(suite.countTestCases() == EXPECTED_METHODS, "qualified bootstrap method count differs")
            result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
        require(not atlas_loaded(), "actual Atlas imports appeared during synthetic controls")
    finally:
        sys.meta_path.remove(guard)
        checked(BASE_BOOTSTRAP, BASE_SHA)
        checked(TEST_SOURCE, TEST_SHA)
        checked(CANDIDATE, args.bootstrap_sha256)
    passed = (result.wasSuccessful() and result.testsRun == EXPECTED_METHODS and
              not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses)
    print(json.dumps({"passed": passed, "selected_controls": EXPECTED_METHODS,
        "tests_run": result.testsRun, "bootstrap_sha256": args.bootstrap_sha256,
        "expected_root": str(TARGET), "expected_counts": counts, "source_finality": True,
        "actual_atlas_imports": False, "native_commands_started": False}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
