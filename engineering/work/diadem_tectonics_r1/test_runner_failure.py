"""Synthetic runner failure and package-binding tests; no legacy execution."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import runner


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_fixture(roles: list[str]) -> dict:
    """Synthetic control identities; empty science fields are never executed."""
    value = {key: [] for key in (
        "history_artifact_filename_templates required_events faults_blocks_layers required_fault_properties "
        "required_block_properties required_structural_model_domain_properties structural_model_domain_contract "
        "fault_block_raster_contract required_crown_link_properties required_massif_properties allowed_node_types "
        "required_crown_system_ids required_titan_component_ids required_master_domain_ids allowed_master_domain_ids "
        "required_npz_arrays required_accommodation_layers required_accommodation_compartment_properties "
        "required_accommodation_ids required_accommodation_edges required_province_ids required_province_properties "
        "required_section_ids required_section_layers section_display_contract hard_thresholds forbidden_lineage_tokens "
        "forbidden_downstream_tokens artificial_island_policy audit_rule").split()}
    value.update({
        "schema_version": "1.0.0-review", "status": "active_fail_closed_audit_contract",
        "checkpoint": "checkpoint-1-structural-geology", "production_authority": False,
        "selected_history": "a", "required_visual_roles": roles,
        "history_selection": {"decision_date": "2026-07-16", "decision_maker": "Michael",
                              "approval_verbatim": "I choose A", "history_b_status": "not_selected_before_implementation"},
        "authority": {
            "checkpoint0_manifest": {"path": runner.sources.CHECKPOINT0,
                                     "sha256": runner.sources.BOOTSTRAP_PINS[runner.sources.CHECKPOINT0]},
            "approved_anchor_option": "transfer_zone_resegmentation",
            "approved_coordinate_order": "peak_anchors.clockwise_order_from_north_west_gate_flank",
            "approved_coordinate_hash_method": "sha256 of clockwise-order x,y pairs as little-endian float64 C-order bytes",
            "approved_coordinate_sha256": runner.sources.COORDINATE_SHA256,
            "anchor_source_review": {"path": runner.sources.ANCHOR, "sha256": runner.sources.ANCHOR_SHA256},
            "anchor_role": "regional Peak-seat reference and containment target only; never summit, structural centroid, Crown endpoint, fault node, divide point, kernel centre or elevation control",
        },
        "shared_manifest_filename": "checkpoint1-event-model-shared-manifest-review-only.json",
        "shared_manifest_required_keys": ["schema_version", "checkpoint", "status", "authority", "histories",
                                          "generator_sources", "production_unchanged", "master_ledger_unchanged"],
    })
    return value


class ReplayFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.originals = self.root / "originals"
        self.engineering = self.root / "engineering"
        self.allowed = self.root / "outputs"
        self.destination = self.allowed / "synthetic-run"
        self.originals.mkdir()
        self.engineering.mkdir()
        self.roles = ["plan_full_frame", "geological_sections"]
        self.events = []
        self.drift_after_comparison = False
        self.reject_final_gate = False
        self.patch(runner.sources, "VISUAL_ROLES", self.roles)
        self.patch(runner.sources, "BOOTSTRAP_PINS", dict(runner.sources.BOOTSTRAP_PINS))

        pins = []
        for name in runner.INPUT_NAMES:
            path = self.originals / name
            if name == runner.INPUT_NAMES[2]:
                runner.sources.BOOTSTRAP_PINS[runner.sources.CHECKPOINT0] = digest(self.originals / runner.INPUT_NAMES[1])
                write_json(path, contract_fixture(self.roles))
            else:
                path.write_bytes(("synthetic retained input: " + name).encode())
            pins.append({
                "relative_path": f"{runner.sources.REBUILD}/{name}",
                "resolved_path": str(path), "expected_sha256": digest(path),
                "actual_sha256": digest(path), "status": "PASS",
            })
        self.source_report = {"status": "PASS", "files": pins}
        for name in ("runner.py", "sources.py", "compare.py", "child_guard.py"):
            (self.engineering / name).write_bytes(("synthetic engineering: " + name).encode())
        self.protected = {
            path: path.read_bytes()
            for directory in (self.originals, self.engineering)
            for path in directory.iterdir()
        }

        self.patch(runner, "ROOT", self.engineering)
        self.patch(runner, "OUTPUT_ROOT", self.allowed)
        self.patch(runner.sources, "SOURCE_ROOT", self.originals)
        self.patch(runner, "runtime_info", return_value={"runtime": "synthetic"})
        self.gate = self.patch(runner.sources, "require_sources", side_effect=self.require_sources)
        self.execute = self.patch(runner, "_execute_legacy", side_effect=self.execute_success)
        self.validate = self.patch(runner, "validate_package", side_effect=self.validate_success)
        self.compare = self.patch(runner, "compare_products", side_effect=self.compare_success)

    def patch(self, target, attribute, *args, **kwargs):
        patcher = mock.patch.object(target, attribute, *args, **kwargs)
        patched = patcher.start()
        self.addCleanup(patcher.stop)
        return patched

    def require_sources(self):
        self.events.append("source_check")
        if self.events.count("source_check") == 3 and self.reject_final_gate:
            raise runner.sources.SourceGateError("synthetic final source gate failure")
        report = copy.deepcopy(self.source_report)
        for item in report["files"]:
            # This fixture checks real tiny source bytes, never legacy paths.
            item["actual_sha256"] = digest(Path(item["resolved_path"]))
            self.assertEqual(item["actual_sha256"], item["expected_sha256"])
        if self.drift_after_comparison:
            # Inject a changed gate observation without mutating any original.
            report["files"][0]["actual_sha256"] = "0" * 64
        return report

    def execute_success(self, script, sandbox):
        self.events.append("execute")
        return subprocess.CompletedProcess(["synthetic-not-executed"], 0, "done\n", "")

    def validate_success(self, sandbox, roles):
        self.events.append("validate")
        return [{"path": "synthetic-only", "sha256": "1" * 64}]

    def compare_success(self, reference, candidate):
        self.events.append("compare")
        return {"status": "PASS", "scope": "synthetic fixture only"}

    def assert_failure(self, *, error_type, stdout=b"", stderr=b"", post_error=None):
        self.assertEqual(self.gate.call_count, 3)
        self.assertEqual(self.events[:2], ["source_check", "source_check"])
        self.assertEqual(self.events[-1], "source_check")
        receipt_path = self.destination / "REPLAY_FAILURE.json"
        self.assertTrue(receipt_path.is_file())
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        self.assertEqual(receipt["status"], "FAILED_OR_BLOCKED")
        self.assertEqual(receipt["error_type"], error_type)
        self.assertIs(receipt["post_source_check_attempted"], True)
        self.assertIs(receipt["production_authority_established"], False)
        if post_error is None:
            self.assertIsNone(receipt["post_source_check_error"])
        else:
            self.assertIn(post_error, receipt["post_source_check_error"])
        self.assertFalse((self.destination / "REPLAY_REPORT.json").exists())
        self.assertEqual((self.destination / "stdout.log").read_bytes(), stdout)
        self.assertEqual((self.destination / "stderr.log").read_bytes(), stderr)
        for path, expected in self.protected.items():
            self.assertEqual(path.read_bytes(), expected, path)
        self.assertEqual(set(self.originals.iterdir()),
                         {path for path in self.protected if path.parent == self.originals})
        self.assertEqual(set(self.engineering.iterdir()),
                         {path for path in self.protected if path.parent == self.engineering})

        # The failure receipt remains readable and an accidental retry cannot
        # replace it, erase logs, or run another source gate or child.
        retained = {path.relative_to(self.destination): path.read_bytes()
                    for path in self.destination.rglob("*") if path.is_file()}
        with self.assertRaisesRegex(runner.ReplayError, "overwrite existing output"):
            runner.replay_review(self.destination)
        self.assertEqual(self.gate.call_count, 3)
        self.assertEqual(receipt_path.read_bytes(), receipt_bytes)
        self.assertEqual(retained, {
            path.relative_to(self.destination): path.read_bytes()
            for path in self.destination.rglob("*") if path.is_file()
        })
        return receipt

    def test_staging_exception_retains_partial_stage_and_final_source_check(self):
        real_copy = runner.copy_verified
        staged = []

        def copy_then_fail(source, destination, expected):
            self.assertEqual(self.gate.call_count, 2)
            self.events.append("stage")
            if staged:
                raise OSError("synthetic staging exception")
            real_copy(source, destination, expected)
            staged.append(destination)

        self.patch(runner, "copy_verified", side_effect=copy_then_fail)
        with self.assertRaisesRegex(runner.ReplayError, "synthetic staging exception"):
            runner.replay_review(self.destination)
        self.assert_failure(error_type="OSError")
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].read_bytes(), self.protected[self.originals / runner.INPUT_NAMES[0]])
        self.execute.assert_not_called()
        self.validate.assert_not_called()
        self.compare.assert_not_called()

    def test_timeout_preserves_partial_binary_stdout_stderr(self):
        stdout, stderr = b"partial stdout\n\xff", b"partial stderr\n\xfe"

        def timeout(*args):
            self.events.append("execute")
            raise subprocess.TimeoutExpired(["synthetic-not-executed"], 1,
                                            output=stdout, stderr=stderr)

        self.execute.side_effect = timeout
        with self.assertRaises(runner.ReplayError):
            runner.replay_review(self.destination)
        self.assert_failure(error_type="TimeoutExpired", stdout=stdout, stderr=stderr)
        self.validate.assert_not_called()
        self.compare.assert_not_called()

    def test_nonzero_child_exit_retains_text_logs_and_final_source_check(self):
        def nonzero(*args):
            self.events.append("execute")
            return subprocess.CompletedProcess(["synthetic-not-executed"], 7,
                                               "partial result\n", "synthetic failure\n")

        self.execute.side_effect = nonzero
        with self.assertRaisesRegex(runner.ReplayError, "failed \\(7\\)"):
            runner.replay_review(self.destination)
        self.assert_failure(error_type="ReplayError", stdout=b"partial result\n",
                            stderr=b"synthetic failure\n")
        self.validate.assert_not_called()
        self.compare.assert_not_called()

    def test_comparison_time_source_drift_blocks_pass_after_comparison(self):
        def compare_with_observed_drift(*args):
            self.events.append("compare")
            self.drift_after_comparison = True
            return {"status": "PASS", "scope": "synthetic fixture only"}

        self.compare.side_effect = compare_with_observed_drift
        with self.assertRaisesRegex(runner.ReplayError, "source or reference identity changed"):
            runner.replay_review(self.destination)
        self.assert_failure(error_type="ReplayError", stdout=b"done\n",
                            post_error="source or reference identity changed")
        self.assertEqual(self.events, ["source_check", "source_check", "execute",
                                      "validate", "compare", "source_check"])
        self.assertEqual(json.loads((self.destination / "logical-comparison.json").read_bytes())["status"], "PASS")
        before = json.loads((self.destination / "sources-before.json").read_bytes())
        after = json.loads((self.destination / "sources-after.json").read_bytes())
        self.assertNotEqual(runner.source_fingerprint(before), runner.source_fingerprint(after))

    def test_comparison_exception_still_checks_sources(self):
        def compare_failure(*args):
            self.events.append("compare")
            raise ValueError("synthetic comparison exception")

        self.compare.side_effect = compare_failure
        with self.assertRaisesRegex(runner.ReplayError, "synthetic comparison exception"):
            runner.replay_review(self.destination)
        self.assert_failure(error_type="ValueError", stdout=b"done\n")
        self.assertFalse((self.destination / "logical-comparison.json").exists())

    def test_final_gate_exception_preserves_primary_child_failure(self):
        self.reject_final_gate = True
        self.execute.side_effect = None
        self.execute.return_value = subprocess.CompletedProcess(
            ["synthetic-not-executed"], 9, "partial\n", "failed\n")
        with self.assertRaisesRegex(runner.ReplayError, "failed \\(9\\)"):
            runner.replay_review(self.destination)
        receipt = self.assert_failure(error_type="ReplayError", stdout=b"partial\n",
                                      stderr=b"failed\n", post_error="synthetic final source gate failure")
        self.assertIn("failed (9)", receipt["error"])
        self.assertFalse((self.destination / "sources-after.json").exists())


class PackageBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sandbox = Path(temporary.name) / "sandbox"
        self.package = self.sandbox / runner.sources.REBUILD
        self.package.mkdir(parents=True)
        self.roles = ["plan_full_frame", "geological_sections"]
        for name in set(runner.INPUT_NAMES) | runner.expected_products(self.roles):
            # These files test manifests, not their numerical/image content.
            (self.package / name).write_bytes(("tiny synthetic product: " + name).encode())
        for patcher in (
            mock.patch.object(runner.sources, "VISUAL_ROLES", self.roles),
            mock.patch.object(runner.sources, "BOOTSTRAP_PINS", {
                **runner.sources.BOOTSTRAP_PINS,
                runner.sources.CHECKPOINT0: digest(self.package / runner.INPUT_NAMES[1]),
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        write_json(self.package / runner.INPUT_NAMES[2], contract_fixture(self.roles))
        self.review_path = self.package / (runner.PREFIX + "visual-review.json")
        write_json(self.review_path, {
            "schema_version": "1.0-review", "history": "A", "status": "PENDING",
            "reviewer_role": "pending_independent",
            "items": [{"role": role, "status": "PENDING", "notes": runner.PENDING_REVIEW_NOTES} for role in self.roles],
        })
        self.visual_path = self.package / (runner.PREFIX + "visual-manifest.json")
        self.visual = {
            "schema_version": "1.0-review", "history": "A",
            "status": "COMPLETE_AWAITING_INDEPENDENT_REVIEW",
            "artifacts": [self.pin(
                f"{runner.sources.REBUILD}/{runner.PREFIX}{role.replace('_', '-')}-review-only.png",
                role=role) for role in self.roles],
        }
        write_json(self.visual_path, self.visual)
        self.shared_path = self.package / "checkpoint1-event-model-shared-manifest-review-only.json"
        self.shared = {
            "schema_version": "1.0-review", "status": "REVIEW_ONLY_NOT_ACCEPTED",
            "checkpoint": "checkpoint-1-structural-geology", "production_unchanged": True,
            "master_ledger_unchanged": True,
            "histories": {
                "A": {"status": "selected_under_review", "artifacts": {
                    role: self.pin(relative) for role, relative in runner.sources.ARTIFACT_PATHS.items()
                }},
                "B": {"status": "not_selected_before_implementation", "artifacts": {}},
            },
            "generator_sources": [self.pin(f"{runner.sources.REBUILD}/{name}")
                                  for name in runner.INPUT_NAMES if name != runner.INPUT_NAMES[1]],
            "authority": runner.expected_authority(),
        }
        write_json(self.shared_path, self.shared)

    def pin(self, relative, **extra):
        return {**extra, "path": relative, "sha256": digest(self.sandbox / relative)}

    def save_visual_and_repin(self):
        write_json(self.visual_path, self.visual)
        self.shared["histories"]["A"]["artifacts"]["visual_manifest"]["sha256"] = digest(self.visual_path)
        write_json(self.shared_path, self.shared)

    def assert_all_declared_hashes_match(self):
        pins = [*self.shared["histories"]["A"]["artifacts"].values(),
                *self.shared["generator_sources"], *self.visual["artifacts"]]
        for pin in pins:
            self.assertEqual(pin["sha256"], digest(self.sandbox / pin["path"]))

    def test_valid_tiny_package_passes_exact_inventory_and_bindings(self):
        self.assert_all_declared_hashes_match()
        records = runner.validate_package(self.sandbox, self.roles)
        expected = {f"{runner.sources.REBUILD}/{name}" for name in
                    set(runner.INPUT_NAMES) | runner.expected_products(self.roles)}
        self.assertEqual({item["path"] for item in records}, expected)
        self.assertEqual(len(records), len(expected))

    def test_swapped_artifact_paths_with_matching_hashes_are_rejected(self):
        artifacts = self.shared["histories"]["A"]["artifacts"]
        artifacts["events"], artifacts["faults_blocks"] = artifacts["faults_blocks"], artifacts["events"]
        write_json(self.shared_path, self.shared)
        self.assert_all_declared_hashes_match()
        with self.assertRaisesRegex(runner.ReplayError, "shared artifact role/path mismatch"):
            runner.validate_package(self.sandbox, self.roles)

    def test_duplicate_visual_paths_with_matching_hashes_are_rejected(self):
        first, second = self.visual["artifacts"]
        second["path"], second["sha256"] = first["path"], first["sha256"]
        self.save_visual_and_repin()
        self.assert_all_declared_hashes_match()
        with self.assertRaisesRegex(runner.ReplayError, "visual role/path mismatch"):
            runner.validate_package(self.sandbox, self.roles)

    def test_swapped_visual_paths_with_matching_hashes_are_rejected(self):
        first, second = self.visual["artifacts"]
        first["path"], second["path"] = second["path"], first["path"]
        first["sha256"], second["sha256"] = second["sha256"], first["sha256"]
        self.save_visual_and_repin()
        self.assert_all_declared_hashes_match()
        with self.assertRaisesRegex(runner.ReplayError, "visual role/path mismatch"):
            runner.validate_package(self.sandbox, self.roles)

    def test_duplicate_source_paths_with_matching_hashes_are_rejected(self):
        self.shared["generator_sources"][1] = copy.deepcopy(self.shared["generator_sources"][0])
        write_json(self.shared_path, self.shared)
        self.assert_all_declared_hashes_match()
        with self.assertRaisesRegex(runner.ReplayError, "shared source inventory differs"):
            runner.validate_package(self.sandbox, self.roles)

    def test_extra_unmanifested_product_is_rejected(self):
        (self.package / "unexpected.bin").write_bytes(b"tiny extra")
        with self.assertRaisesRegex(runner.ReplayError, "unexpected package inventory"):
            runner.validate_package(self.sandbox, self.roles)


if __name__ == "__main__":
    unittest.main()
