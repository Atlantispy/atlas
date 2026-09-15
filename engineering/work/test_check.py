"""Small runner-control checks, not a rerun of generator science."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from work import check


class ShortcutTests(unittest.TestCase):
    def fixture(self, method, *, empty=False, errors=()):
        case = type("Example", (unittest.TestCase,), {"test_case": method})
        class Loader:
            def loadTestsFromNames(inner, names):
                inner.names = names
                return unittest.TestSuite([] if empty else [case("test_case")])
        loader = Loader()
        loader.errors = list(errors)
        return loader

    def test_exact_selection_deduplicates_and_rejects_unknown_or_empty(self):
        self.assertEqual(check.select(["parents", "parents", "executor"]), ["parents", "executor"])
        for names in ([], ["everything"], ["parents", "bad"]):
            with self.assertRaises(ValueError):
                check.select(names)

    def test_success_runs_only_selected_module_and_labels_scope(self):
        loader = self.fixture(lambda self: None)
        report = check.run(["parents"], loader=loader, stream=io.StringIO())
        self.assertEqual(loader.names, [check.TARGETS["parents"]])
        self.assertEqual((report["status"], report["executed_tests"]), ("PASS", 1))
        self.assertFalse(report["full_generator_verification"])
        self.assertEqual(report["scope"], "FOCUSED_DEVELOPMENT_ONLY")
        self.assertGreaterEqual(report["elapsed_seconds"], 0)

    def test_failure_is_not_a_pass(self):
        report = check.run(["parents"], loader=self.fixture(lambda self: self.fail("expected probe")),
                           stream=io.StringIO())
        self.assertEqual(report["status"], "FAIL")

    def test_skipped_test_is_incomplete(self):
        report = check.run(["parents"], loader=self.fixture(lambda self: self.skipTest("probe")),
                           stream=io.StringIO())
        self.assertEqual(report["status"], "INCOMPLETE")

    def test_discovery_error_or_empty_selection_never_passes(self):
        for loader in (self.fixture(lambda self: None, empty=True),
                       self.fixture(lambda self: None, errors=["broken import"])):
            with self.assertRaises(ValueError):
                check.run(["parents"], loader=loader, stream=io.StringIO())

    def test_list_does_not_import_or_run_tests(self):
        output = io.StringIO()
        with patch.object(check, "prepare_imports") as prepare, patch.object(check, "run") as run:
            with contextlib.redirect_stdout(output):
                self.assertEqual(check.main(["parents", "--list"]), 0)
            prepare.assert_not_called()
            run.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "NOT_RUN")

    def test_command_failure_and_import_error_return_nonzero(self):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(check, "prepare_imports"):
            with patch.object(check, "run", return_value={"status": "FAIL"}):
                self.assertEqual(check.main(["parents"]), 1)
        with contextlib.redirect_stdout(io.StringIO()):
            with patch.object(check, "prepare_imports", side_effect=ValueError("bad import")):
                self.assertEqual(check.main(["parents"]), 1)
