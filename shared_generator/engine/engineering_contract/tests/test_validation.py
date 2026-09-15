from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from diadem_contract.evidence import benchmark_record, metric_set
from diadem_contract.validation import validate_bundle, validate_document


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "examples/evidence"


class EvidenceValidationTests(unittest.TestCase):
    def test_all_evidence_examples_validate(self):
        report = validate_bundle(EVIDENCE)
        self.assertTrue(report["passed"], report)
        self.assertEqual(len(report["results"]), 5)

    def test_pass_cancellation_cannot_claim_lost_commit(self):
        document = json.loads((EVIDENCE / "cancellation.example.json").read_text(encoding="utf-8"))
        document["observed"]["last_committed_digest_preserved"] = False
        result = validate_document(document)
        self.assertFalse(result.passed)

    def test_pass_corruption_requires_authority_rebuild_and_unaffected_recovery(self):
        document = json.loads((EVIDENCE / "corruption.example.json").read_text(encoding="utf-8"))
        document["observed"]["rebuilt_from_authority"] = False
        document["observed"]["unaffected_data_recovered"] = False
        result = validate_document(document)
        self.assertFalse(result.passed)

    def test_pass_fallback_requires_reason_and_telemetry(self):
        document = json.loads((EVIDENCE / "fallback.example.json").read_text(encoding="utf-8"))
        document["fallback"]["reason_recorded"] = False
        document["fallback"]["telemetry_recorded"] = False
        result = validate_document(document)
        self.assertFalse(result.passed)

    def test_adopt_cannot_validate_without_resolved_typed_evidence(self):
        adoption = json.loads((EVIDENCE / "adoption.example.json").read_text(encoding="utf-8"))
        self.assertFalse(validate_document(adoption).passed)
        wrong_type = json.loads((EVIDENCE / "corruption.example.json").read_text(encoding="utf-8"))
        wrong_type["test_id"] = adoption["evidence"]["benchmark_id"]
        self.assertFalse(validate_document(adoption, evidence_documents=[wrong_type]).passed)

    def test_adopt_rejects_duplicate_matching_evidence(self):
        adoption = json.loads((EVIDENCE / "adoption.example.json").read_text(encoding="utf-8"))
        documents = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in EVIDENCE.glob("*.json")
            if path.name != "adoption.example.json"
        ]
        benchmark = next(item for item in documents if item["schema"] == "diadem.engineering.benchmark.v1")
        documents.append(copy.deepcopy(benchmark))
        self.assertFalse(validate_document(adoption, evidence_documents=documents).passed)

    def test_adopt_rejects_schema_invalid_matching_evidence(self):
        adoption = json.loads((EVIDENCE / "adoption.example.json").read_text(encoding="utf-8"))
        documents = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in EVIDENCE.glob("*.json")
            if path.name != "adoption.example.json"
        ]
        benchmark = next(item for item in documents if item["schema"] == "diadem.engineering.benchmark.v1")
        del benchmark["candidate"]["metrics"]["peak_ram_bytes"]
        self.assertFalse(validate_document(adoption, evidence_documents=documents).passed)

    def test_adoption_fails_closed_below_gain_threshold(self):
        document = json.loads((EVIDENCE / "adoption.example.json").read_text(encoding="utf-8"))
        document["observed"]["end_to_end_gain_fraction"] = 0.01
        result = validate_document(document)
        self.assertFalse(result.passed)

    def test_benchmark_requires_three_repetitions_and_all_metrics(self):
        document = json.loads((EVIDENCE / "benchmark.example.json").read_text(encoding="utf-8"))
        document["candidate"]["runs"] = 1
        del document["candidate"]["metrics"]["peak_ram_bytes"]
        result = validate_document(document)
        self.assertFalse(result.passed)
        paths = {issue.path for issue in result.issues}
        self.assertIn("$.candidate.runs", paths)
        self.assertIn("$.candidate.metrics.peak_ram_bytes", paths)

    def test_executable_benchmark_builder_computes_end_to_end_gain(self):
        fingerprint = "dgh:v1:raster:sha256:" + "a" * 64
        reference = metric_set(
            wall_seconds=10.0,
            cpu_seconds=9.0,
            peak_ram_bytes=100,
            disk_read_bytes=20,
            disk_write_bytes=10,
            files_opened=3,
            data_read_bytes=20,
            output_bytes=5,
            context_bytes=None,
            estimated_context_tokens=None,
            disk_read_operations=4,
            disk_write_operations=2,
            measurement_methods={
                "context_bytes": {"basis": "NOT_MEASURABLE", "method": "No model context."},
                "estimated_context_tokens": {"basis": "NOT_MEASURABLE", "method": "No model context."},
                "disk_read_operations": {"basis": "MEASURED", "method": "Process counter."},
                "disk_write_operations": {"basis": "MEASURED", "method": "Process counter."},
            },
        )
        candidate = dict(reference)
        candidate["wall_seconds"] = 8.0
        document = benchmark_record(
            benchmark_id="builder-test",
            task={
                "name": "same task",
                "semantic_input_fingerprint": "dgh:v1:manifest:sha256:" + "b" * 64,
            },
            environment={"class": "PINNED"},
            reference_path_id="reference",
            candidate_path_id="candidate",
            reference_metrics=reference,
            candidate_metrics=candidate,
            reference_output_fingerprints=[fingerprint],
            candidate_output_fingerprints=[fingerprint],
            runs=3,
            artifact_family="floating_array_pinned",
            parity_report_fingerprint="dgh:v1:parity-report:sha256:" + "c" * 64,
            parity_pass=True,
            resource_limits_pass=True,
        )
        self.assertAlmostEqual(document["comparison"]["end_to_end_gain_fraction"], 0.2)
        self.assertEqual(document["status"], "PASS")

    def test_not_measurable_metric_requires_null_not_fake_zero(self):
        document = json.loads((EVIDENCE / "benchmark.example.json").read_text(encoding="utf-8"))
        document["candidate"]["metrics"]["context_bytes"] = 0
        result = validate_document(document)
        self.assertFalse(result.passed)
        self.assertIn("$.candidate.metrics.context_bytes", {issue.path for issue in result.issues})

    def test_measured_metric_cannot_be_null(self):
        document = json.loads((EVIDENCE / "benchmark.example.json").read_text(encoding="utf-8"))
        document["candidate"]["metrics"]["disk_read_operations"] = None
        result = validate_document(document)
        self.assertFalse(result.passed)
        self.assertIn("$.candidate.metrics.disk_read_operations", {issue.path for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
