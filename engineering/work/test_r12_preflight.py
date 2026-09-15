"""Focused startup checks using doubles; no scientific generation."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from work.generator_runtime_r12 import __main__ as cli, integration, provenance


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r12-preflight-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "result"

    def invoke(self, extra=()):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return cli.main(["--output", str(self.output), *extra])

    def test_bad_numeric_options_fail_before_loading_science_or_creating_output(self):
        cases = [("--workers", "0"), ("--workers", "-1"), ("--workers", "1.5"),
                 ("--memory-budget-mb", "0"), ("--worker-memory-mb", "-2"),
                 ("--memory-budget-mb", "100", "--worker-memory-mb", "101"),
                 ("--stop-after", "-1")]
        with patch.object(provenance, "load_science") as load:
            for args in cases:
                with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                    self.invoke(args)
                self.assertEqual(error.exception.code, 2)
                self.assertFalse(self.output.exists())
            load.assert_not_called()

    def test_api_bad_options_fail_before_loading_sources_or_cache(self):
        cases = [{"workers": False}, {"workers": 0}, {"memory_budget_mb": 0},
                 {"worker_memory_mb": True}, {"memory_budget_mb": 1},
                 {"stop_after": -1}, {"decoded_bytes": -1}, {"decoded_bytes": None},
                 {"recipe": []}, {"resume": []}, {"supplied_parent": []}]
        with patch.object(provenance, "load_science") as load, patch.object(integration, "Store") as store:
            for options in cases:
                with self.subTest(options=options), self.assertRaises(ValueError):
                    integration.run_workflow(**options)
            load.assert_not_called()
            store.assert_not_called()

    def test_valid_boundary_options(self):
        integration.validate_options(workers=1, memory_budget_mb=1, worker_memory_mb=1,
                                     stop_after=0, decoded_bytes=0)
        integration.validate_options(workers=16, memory_budget_mb=1024, worker_memory_mb=512)

    def test_bad_input_json_or_missing_file_fails_before_science(self):
        input_path = self.root / "input.json"
        with patch.object(provenance, "load_science") as load:
            for option in ("--recipe", "--parent", "--resume"):
                for raw in ("{broken", "[]", "null"):
                    input_path.write_text(raw, encoding="utf-8")
                    with self.subTest(option=option, raw=raw), self.assertRaises(SystemExit):
                        self.invoke([option, str(input_path)])
                    self.assertFalse(self.output.exists())
            with self.assertRaises(SystemExit):
                self.invoke(["--recipe", str(self.root / "absent.json")])
            load.assert_not_called()

    def test_existing_output_is_preserved_without_loading_science(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("original", encoding="utf-8")
        with patch.object(provenance, "load_science") as load, self.assertRaises(SystemExit):
            self.invoke()
        load.assert_not_called()
        self.assertEqual(marker.read_text(encoding="utf-8"), "original")

    def test_relative_output_or_cache_fails_before_science(self):
        with patch.object(provenance, "load_science") as load:
            with self.assertRaises(SystemExit):
                self.invoke(["--cache", "relative-cache"])
            self.output = Path("relative-result")
            with self.assertRaises(SystemExit):
                self.invoke()
            load.assert_not_called()

    def bundle(self):
        scientific = {"status": "EXECUTED", "example": "unchanged"}
        storage = SimpleNamespace(
            plain_path=lambda path: Path(path),
            read_json=lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
            write_json=lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8"))
        verifier = SimpleNamespace(persist_workflow=Mock(return_value={"saved": True}),
                                   read_workflow=Mock(return_value=scientific))
        bundle = SimpleNamespace(storage=storage, reference=SimpleNamespace(recipe=lambda _: {"recipe": True}),
                                 module=Mock(return_value=verifier), run_workflow=Mock(return_value=scientific))
        return bundle, scientific

    def test_authoritative_reader_failure_still_prevents_output_creation(self):
        bundle, _ = self.bundle()
        input_path = self.root / "input.json"
        input_path.write_text('{"duplicate":1,"duplicate":2}', encoding="utf-8")
        bundle.storage.read_json = Mock(side_effect=ValueError("sealed reader rejects duplicate key"))
        with patch.object(provenance, "load_science", return_value=bundle), \
                patch.object(integration, "run_workflow") as run, self.assertRaises(ValueError):
            self.invoke(["--recipe", str(input_path)])
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_computation_failure_leaves_no_result_directory(self):
        bundle, _ = self.bundle()
        with patch.object(provenance, "load_science", return_value=bundle), \
                patch.object(integration, "run_workflow", side_effect=ValueError("bad scientific recipe")), \
                self.assertRaises(ValueError):
            self.invoke()
        self.assertFalse(self.output.exists())

    def test_successful_candidate_creates_output_only_after_run_and_preserves_arguments(self):
        bundle, scientific = self.bundle()
        def run(recipe, **options):
            self.assertFalse(self.output.exists())
            self.assertEqual(recipe, {"recipe": True})
            self.assertEqual(options["workers"], 2)
            self.assertEqual(options["memory_budget_mb"], 1024)
            self.assertEqual(options["stop_after"], 0)
            self.assertIsNone(options["cache_root"])
            return {"scientific": scientific, "execution": {"elapsed_wall_seconds": 0.1}}
        with patch.object(provenance, "load_science", return_value=bundle), \
                patch.object(integration, "run_workflow", side_effect=run):
            self.invoke(["--workers", "2", "--no-cache", "--stop-after", "0"])
        self.assertTrue((self.output / "execution.json").is_file())
        self.assertEqual(bundle.module.return_value.persist_workflow.call_args.args[2], scientific)

    def test_reference_path_remains_available(self):
        bundle, scientific = self.bundle()
        def run(*args, **kwargs):
            self.assertFalse(self.output.exists())
            return scientific
        bundle.run_workflow.side_effect = run
        with patch.object(provenance, "load_science", return_value=bundle), \
                patch.object(integration, "run_workflow") as candidate:
            self.invoke(["--reference"])
        candidate.assert_not_called()
        self.assertTrue((self.output / "scientific-record.json").is_file())

    def test_concurrently_created_output_is_never_overwritten(self):
        bundle, scientific = self.bundle()
        def run(*args, **kwargs):
            self.output.mkdir()
            (self.output / "keep.txt").write_text("other", encoding="utf-8")
            return {"scientific": scientific, "execution": {"elapsed_wall_seconds": 0.1}}
        with patch.object(provenance, "load_science", return_value=bundle), \
                patch.object(integration, "run_workflow", side_effect=run), self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual((self.output / "keep.txt").read_text(encoding="utf-8"), "other")
        self.assertFalse((self.output / "execution.json").exists())
