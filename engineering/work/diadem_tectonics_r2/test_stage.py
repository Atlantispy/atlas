"""Synthetic orchestration/failure tests; no historical producer execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import stage


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="diadem_stage_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output_root = self.root / "outputs"
        self.output = self.output_root / "new"
        self.parent = self.root / "parent"
        self.package = self.parent / "package"
        self.source = {"status": "PASS", "synthetic": True}
        self.receipt = {"root": str(self.parent), "synthetic": True}
        self.snapshot = {"products": {name: {"synthetic": name}
                                     for name in stage.PRODUCT_NAMES},
                         "validation": {"status": "INCOMPLETE", "category_complete": False,
                                        "production_authorized": False}}
        self.addCleanup(patch.stopall)
        patch.object(stage, "OUTPUT_ROOT", self.output_root).start()
        self.require_sources = patch.object(stage.sources, "require_sources", return_value=self.source).start()
        patch.object(stage.replay, "source_fingerprint", side_effect=lambda x: x).start()
        self.verify = patch.object(stage, "verify_structure_run", return_value=(self.package, self.receipt)).start()
        self.scope = patch.object(stage, "recovered_scope", return_value={"status": "PASS_EVIDENCE_CLOSURE", "synthetic": True}).start()
        self.identity = patch.object(stage, "code_identity", return_value={"synthetic": "code"}).start()
        patch.object(stage, "runtime_identity", return_value={"synthetic": "runtime"}).start()
        self.builder = patch.object(stage, "build_snapshot", return_value=self.snapshot).start()
        self.compare = patch.object(stage, "compare_products", return_value={"status": "PASS"}).start()
        self.audit = patch.object(stage, "audit_package", return_value={"overall_status": "PASS"}).start()

    def run_stage(self, **kwargs):
        return stage.build_review(self.parent, self.output, **kwargs)

    def read(self, name):
        return json.loads((self.output / name).read_text(encoding="utf-8"))

    def write_input(self, name, value):
        path = self.root / name
        stage.replay.write_json(path, value)
        return path

    def assert_failure_receipt(self):
        self.assertFalse((self.output / "STAGE_REPORT.json").exists())
        receipt = self.read("STAGE_FAILURE.json")
        self.assertFalse(receipt["category_complete"])
        self.assertFalse(receipt["production_authorized"])
        self.assertTrue(receipt["post_checks_attempted"])

    def test_review_assembly_never_promotes_stage(self):
        result = self.run_stage()
        self.assertEqual(result["engineering_assembly"], "PASS")
        self.assertEqual(result["status"], "INCOMPLETE_DOMAIN_AUTHORITY")
        self.assertFalse(result["category_complete"])
        report = self.read("STAGE_REPORT.json")
        self.assertFalse(report["production_authorized"])
        self.assertTrue(report["protected_inputs_unchanged"])
        self.assertEqual({v["path"] for v in report["products"]}, stage.PRODUCT_NAMES)
        for product in report["products"]:
            path = self.output / product["path"]
            self.assertEqual(stage.file_hash(path), product["sha256"])

    def test_scientific_failure_is_retained_not_hidden(self):
        self.audit.return_value = {"overall_status": "FAIL"}
        result = self.run_stage()
        self.assertEqual(result["status"], "BLOCKED_SCIENTIFIC_REVIEW")
        self.assertEqual(self.read("independent-audit.json")["overall_status"], "FAIL")

    def test_scientific_blocked_is_retained(self):
        self.audit.return_value = {"overall_status": "BLOCKED"}
        self.assertEqual(self.run_stage()["status"], "BLOCKED_SCIENTIFIC_REVIEW")

    def test_preflight_source_failure_creates_no_output(self):
        self.require_sources.side_effect = stage.sources.SourceGateError("synthetic changed source")
        with self.assertRaises(stage.sources.SourceGateError):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_incompatible_snapshot_inventory_creates_no_output(self):
        self.builder.return_value = {"products": {"extra.json": {}}}
        with self.assertRaisesRegex(stage.StageError, "inventory"):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_bad_decisions_create_no_output(self):
        self.builder.side_effect = ValueError("synthetic invalid decision")
        with self.assertRaises(ValueError):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_no_clobber_existing_directory(self):
        self.output.mkdir(parents=True)
        with self.assertRaisesRegex(stage.StageError, "never overwritten"):
            self.run_stage()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_output_root_and_escape_rejected(self):
        for path in (self.output_root, self.root / "elsewhere", self.output_root / ".." / "escape"):
            with self.subTest(path=path), self.assertRaises((stage.StageError, ValueError, RuntimeError, OSError)):
                stage.confined_new_output(path)

    def test_unknown_auditor_status_is_failure(self):
        self.audit.return_value = {"status": "READY"}
        with self.assertRaisesRegex(stage.StageError, "explicit PASS"):
            self.run_stage()
        self.assert_failure_receipt()

    def test_auditor_exception_records_failure_and_runs_postchecks(self):
        self.audit.side_effect = ValueError("synthetic geometry error")
        with self.assertRaisesRegex(stage.StageError, "geometry"):
            self.run_stage()
        self.assertEqual(self.require_sources.call_count, 2)
        self.assert_failure_receipt()

    def test_interruption_records_failure_and_reraises(self):
        self.audit.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_stage()
        self.assert_failure_receipt()

    def test_parity_failure_is_not_audit_pass(self):
        self.compare.return_value = {"status": "FAIL"}
        with self.assertRaisesRegex(stage.StageError, "comparison failed"):
            self.run_stage()
        self.audit.assert_not_called()
        self.assert_failure_receipt()

    def test_source_mutation_fails_postcheck(self):
        self.require_sources.side_effect = [self.source, {"status": "PASS", "synthetic": "mutated"}]
        with self.assertRaisesRegex(stage.StageError, "changed"):
            self.run_stage()
        self.assert_failure_receipt()

    def test_parent_mutation_fails_postcheck(self):
        self.verify.side_effect = [(self.package, self.receipt), (self.package, {"root": "changed"})]
        with self.assertRaisesRegex(stage.StageError, "changed"):
            self.run_stage()
        self.assert_failure_receipt()

    def test_code_mutation_fails(self):
        self.identity.side_effect = [{"synthetic": "first"}, {"synthetic": "changed"}]
        with self.assertRaisesRegex(stage.StageError, "implementation changed"):
            self.run_stage()
        self.assert_failure_receipt()

    def test_recovered_scope_mutation_fails(self):
        self.scope.side_effect = [{"status": "PASS_EVIDENCE_CLOSURE"}, {"status": "CHANGED"}]
        with self.assertRaisesRegex(stage.StageError, "changed"):
            self.run_stage()
        self.assert_failure_receipt()

    def test_recovered_scope_preflight_failure_creates_no_output(self):
        self.scope.side_effect = ValueError("synthetic changed accepted source")
        with self.assertRaisesRegex(ValueError, "accepted source"):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_recovered_scope_incompatible_status_creates_no_output(self):
        self.scope.return_value = {"status": "PENDING"}
        with self.assertRaisesRegex(stage.StageError, "closure did not pass"):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_post_source_gate_exception_records_failure(self):
        self.require_sources.side_effect = [self.source, OSError("synthetic inaccessible source")]
        with self.assertRaisesRegex(stage.StageError, "inaccessible"):
            self.run_stage()
        self.assert_failure_receipt()
        self.assertIsNotNone(self.read("STAGE_FAILURE.json")["post_check_error"])

    def test_bound_visual_change_during_audit_fails(self):
        visual = self.write_input("visual.json", {"synthetic": "review"})
        def change_review(*args):
            visual.write_text("{}", encoding="utf-8")
            return {"overall_status": "PASS"}
        self.audit.side_effect = change_review
        with self.assertRaisesRegex(stage.StageError, "review/decision input changed"):
            self.run_stage(visual_review_path=visual)
        self.assert_failure_receipt()

    def test_output_write_failure_cannot_leave_pass_receipt(self):
        writer = stage.replay.write_json
        def fail_one(path, value):
            if Path(path).name == "snapshot-validation.json":
                raise OSError("synthetic disk failure")
            return writer(path, value)
        with patch.object(stage.replay, "write_json", side_effect=fail_one):
            with self.assertRaisesRegex(stage.StageError, "disk failure"):
                self.run_stage()
        self.assert_failure_receipt()

    def test_bind_json_rejects_duplicate_keys(self):
        path = self.root / "duplicate.json"
        path.write_text('{"a":1,"a":2}', encoding="utf-8")
        with self.assertRaises((ValueError, stage.replay.ReplayError, stage.sources.SourceGateError)):
            stage.bind_json(path)

    def test_final_receipt_write_failure_records_failure(self):
        writer = stage.replay.write_json
        def fail_final(path, value):
            if Path(path).name == ".STAGE_REPORT.pending.json":
                raise OSError("synthetic final-report failure")
            return writer(path, value)
        with patch.object(stage.replay, "write_json", side_effect=fail_final):
            with self.assertRaisesRegex(stage.StageError, "final-report"):
                self.run_stage()
        self.assert_failure_receipt()
        self.assertEqual(self.read("STAGE_FAILURE.json")["failure_phase"], "final_report_publication")

    def test_exact_source_bytes_do_not_verify_approval(self):
        path = self.write_input("evidence.json", {"status": "synthetic"})
        refs = {"source_refs": [{"id": "synthetic", "path": str(path),
                                "sha256": stage.file_hash(path), "locator": "fixture only"}]}
        result = stage.bind_decision_sources(refs)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["authority_claim_verified"])
        refs["source_refs"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(stage.StageError, "changed"):
            stage.bind_decision_sources(refs)

    def test_source_locator_is_mandatory(self):
        path = self.write_input("evidence.json", {})
        refs = {"source_refs": [{"path": str(path), "sha256": stage.file_hash(path), "locator": " "}]}
        with self.assertRaisesRegex(stage.StageError, "locator"):
            stage.bind_decision_sources(refs)

    def test_write_product_rejects_uncontracted_names(self):
        self.output.mkdir(parents=True)
        for name in ("extra.json", "../extra.json", "sub/file.json", "bad:stream", ""):
            with self.subTest(name=name), self.assertRaises(stage.StageError):
                stage.write_product(self.output, name, {})


if __name__ == "__main__":
    unittest.main()
