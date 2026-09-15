import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import runner
from test_runner_failure import contract_fixture


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowed = self.root / "outputs"
        self.patch = mock.patch.object(runner, "OUTPUT_ROOT", self.allowed)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_new_child_allowed(self):
        self.assertEqual(runner.confined_output(self.allowed / "run1"), self.allowed / "run1")

    def test_outputs_root_denied(self):
        with self.assertRaises(runner.ReplayError):
            runner.confined_output(self.allowed)

    def test_outside_denied(self):
        with self.assertRaises(runner.ReplayError):
            runner.confined_output(self.root / "source")

    def test_traversal_denied(self):
        with self.assertRaises(runner.ReplayError):
            runner.confined_output(self.allowed / ".." / "outputs" / "run")

    def test_existing_output_preserved(self):
        destination = self.allowed / "run1"
        destination.mkdir(parents=True)
        with self.assertRaises(runner.ReplayError):
            runner.confined_output(destination)
        self.assertTrue(destination.exists())

    def test_source_failure_creates_nothing(self):
        with mock.patch.object(runner.sources, "require_sources", side_effect=runner.sources.SourceGateError("drift")), mock.patch.object(runner, "_execute_legacy") as execute:
            with self.assertRaises(runner.sources.SourceGateError):
                runner.replay_review(self.allowed / "run1")
        execute.assert_not_called()
        self.assertFalse(self.allowed.exists())

    def test_reparse_path_denied(self):
        fake = mock.Mock(st_mode=0, st_file_attributes=0x400)
        with mock.patch.object(Path, "lstat", return_value=fake):
            with self.assertRaises(runner.ReplayError):
                runner.confined_output(self.allowed / "run1")

    def test_copy_drift_fails_before_write(self):
        source = self.root / "input"
        source.write_bytes(b"changed")
        output = self.root / "out"
        with self.assertRaises(runner.ReplayError):
            runner.copy_verified(source, output, hashlib.sha256(b"original").hexdigest())
        self.assertFalse(output.exists())

    def test_copy_verified_bytes(self):
        source = self.root / "input"
        source.write_bytes(b"original")
        output = self.root / "out"
        runner.copy_verified(source, output, hashlib.sha256(b"original").hexdigest())
        self.assertEqual(output.read_bytes(), source.read_bytes())

    def test_write_new_never_overwrites(self):
        path = self.root / "existing"
        path.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            runner.write_new(path, b"replacement")
        self.assertEqual(path.read_bytes(), b"preserve")

    def test_empty_or_duplicate_roles_rejected(self):
        for roles in ([], ["plan", "plan"], ["../escape"], ["plan/escape"], None, "plan", [3]):
            with self.subTest(roles=roles), self.assertRaises(runner.ReplayError):
                runner.expected_products(roles)

    def test_products_include_all_visuals_and_numerical_files(self):
        products = runner.expected_products(["plan", "section"])
        self.assertEqual(len(products), 14)
        self.assertIn(runner.PREFIX + "plan-review-only.png", products)
        self.assertIn(runner.PREFIX + "structural-fields.npz", products)

    def test_incomplete_candidate_cannot_validate(self):
        sandbox = self.root / "sandbox"
        sandbox.mkdir()
        with self.assertRaises(runner.ReplayError):
            runner.validate_package(sandbox, ["plan"])

    def test_report_json_rejects_nonfinite(self):
        with self.assertRaises(ValueError):
            runner.write_json(self.root / "report", {"x": float("nan")})
        self.assertFalse((self.root / "report").exists())

    def test_prior_visual_pass_cannot_be_reused(self):
        sandbox = self.root / "sandbox"
        package = sandbox / runner.sources.REBUILD
        package.mkdir(parents=True)
        for name in set(runner.INPUT_NAMES) | runner.expected_products(["plan"]):
            (package / name).write_bytes(b"{}")
        (package / runner.INPUT_NAMES[2]).write_text(json.dumps(contract_fixture(["plan"])), encoding="utf-8")
        (package / (runner.PREFIX + "visual-review.json")).write_text(json.dumps({
            "status": "PASS", "items": [{"role": "plan", "status": "PASS"}]
        }))
        with mock.patch.object(runner.sources, "VISUAL_ROLES", ["plan"]), self.assertRaisesRegex(runner.ReplayError, "historical visual PASS"):
            runner.validate_package(sandbox, ["plan"])


if __name__ == "__main__":
    unittest.main()
