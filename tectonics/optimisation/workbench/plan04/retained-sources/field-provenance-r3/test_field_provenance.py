"""Data-only source pin/call-site/reader binding faults; no native runtime import."""
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("field_provenance", HERE / "field_provenance.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
BASE = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/ps/c")
W = "atlas_tectonics/integration_wall_measures.py"
E = "atlas_tectonics/integration_exterior_mesh.py"


def pack(record):
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return {"raw": raw, "identity": sha256(raw).hexdigest()}


def encoded(integer):
    return [hex(integer), "0x1"]


class LazyRows(Mapping):
    def __init__(self, row):
        self.row, self.reads = row, 0

    def __len__(self):
        return 1

    def __iter__(self):
        return iter(("mesh",))

    def __getitem__(self, key):
        if key != "mesh":
            raise KeyError(key)
        self.reads += 1
        return self.row


class ProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_sources = {
            "before": {name: (BASE / "full6/src" / name).read_bytes() for name in (W, E)},
            "after": {name: (BASE / "wr2/src" / name).read_bytes() for name in (W, E)},
        }

    def setUp(self):
        self.manifests = {"before": "a" * 64, "after": "b" * 64}
        self.raw = deepcopy(self.raw_sources)
        self.pins = {arm: {path: sha256(raw).hexdigest() for path, raw in files.items()}
                     for arm, files in self.raw.items()}
        self.record = {
            "schema": P.MESH,
            "representative_quaternion": [encoded(1), encoded(0), encoded(0), encoded(0)],
            "pose_operator_error_bound": encoded(0),
            "trajectory_id": "c" * 64, "trajectory_segments": [],
            "cells": [{"unrelated_large_record_content": "discard after processing"}],
        }
        self.records = {arm: {"mesh": pack(self.record)} for arm in self.manifests}
        pin = self.records["before"]["mesh"]["identity"]
        self.pairs = [(pin, pin)]

    def context(self):
        return P.Context(self.manifests, self.pins, self.raw, self.records, self.pairs)

    def report(self):
        return P.assess_records(self.manifests, self.pins, self.raw, self.records, self.pairs)

    def test_actual_source_calls_and_five_mandatory_slots(self):
        context = self.context()
        self.assertEqual(set(context.slots), set(P.SLOTS))
        for catalog in context.catalogs.values():
            self.assertEqual(len(catalog["W"]["call_sites"]), 3)
            self.assertEqual(len(catalog["E"]["call_sites"]), 2)
            self.assertTrue(all(row["ast_sha256"] for row in catalog["W"]["call_sites"]))

    def test_identical_records_do_not_waive_missing_producer_context(self):
        report = self.report()
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertEqual(len(report["receipts"]), 5)
        self.assertTrue(report["issues"])
        for receipt in report["receipts"]:
            self.assertIn("NO_AUTHENTICATED_PRODUCER_INVOCATION_CONTEXT", receipt["issues"])
            self.assertIsNone(receipt["comparison_bound"])
            self.assertIsNone(receipt["applicable_radius"])

    def test_source_bytes_drift_fails(self):
        self.raw["after"][W] += b"# drift"
        self.assertEqual(self.report()["verdict"], "FAIL")

    def test_unknown_real_selected_source_is_review_not_inferred_semantics(self):
        self.raw["after"][W] += b"# new unreviewed producer"
        self.pins["after"][W] = sha256(self.raw["after"][W]).hexdigest()
        report = self.report()
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertTrue(any("UNREVIEWED_SELECTED_PRODUCER" in issue for issue in report["issues"]))

    def test_ambiguous_source_family_fails(self):
        self.pins["before"]["other/" + W] = self.pins["before"][W]
        self.raw["before"]["other/" + W] = self.raw["before"][W]
        self.assertEqual(self.report()["verdict"], "FAIL")

    def test_extra_or_missing_source_bytes_fail(self):
        self.raw["before"]["not_selected.py"] = b""
        self.assertEqual(self.report()["verdict"], "FAIL")
        del self.raw["before"]["not_selected.py"]
        del self.raw["before"][W]
        self.assertEqual(self.report()["verdict"], "FAIL")

    def test_record_hash_mismatch_fails(self):
        self.records["after"]["mesh"]["raw"] += b" "
        self.assertEqual(self.report()["verdict"], "FAIL")

    def test_duplicate_json_keys_fail_even_with_correct_hash(self):
        raw = b'{"schema":"one","schema":"two"}'
        self.records["after"]["mesh"] = {"raw": raw, "identity": sha256(raw).hexdigest()}
        self.assertEqual(self.report()["verdict"], "FAIL")

    def test_missing_arm_fails(self):
        del self.records["after"]
        self.assertEqual(self.report()["verdict"], "FAIL")

    def test_missing_reader_correspondence_is_explicit(self):
        self.pairs = []
        report = self.report()
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertTrue(any("INDEPENDENT_RECORD_CORRESPONDENCE_MISSING" in item for item in report["issues"]))

    def test_record_history_is_bound_not_invented(self):
        del self.record["trajectory_id"]
        self.records = {arm: {"mesh": pack(self.record)} for arm in self.manifests}
        report = self.report()
        self.assertTrue(any("SOURCE_HISTORY_CONTEXT_MISSING" in item for item in report["issues"]))

    def test_missing_known_output_remains_mandatory(self):
        del self.record["representative_quaternion"]
        self.records = {arm: {"mesh": pack(self.record)} for arm in self.manifests}
        report = self.report()
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertTrue(any("MANDATORY_OUTPUT_FIELD_MISSING" in item for item in report["issues"]))

    def test_nonexact_pose_encoding_fails(self):
        self.record["representative_quaternion"] = [1.0, 0.0, 0.0, 0.0]
        self.records["after"]["mesh"] = pack(self.record)
        self.assertEqual(self.report()["verdict"], "FAIL")

    def test_operator_error_never_becomes_quaternion_radius(self):
        context = self.context()
        receipt = P.emit_receipt("E.representative-quaternion", context)
        self.assertIsNone(receipt["applicable_radius"])
        self.assertEqual(receipt["quantity"]["norm"], "l2")
        self.assertEqual(P.emit_receipt("E.pose-operator-error", context)["quantity"]["norm"], "scalar")
        self.assertIn("4*internal", receipt["arms"]["before"]["outputs"][0]["error"]["meaning"])

    def test_receipt_rederivation_rejects_asserted_source_call_output_and_context(self):
        context = self.context()
        receipt = P.emit_receipt("E.representative-quaternion", context)
        self.assertEqual(P.validate_receipt(receipt, context)["verdict"], "REVIEW")
        variants = []
        for field, value in (("applicable_radius", ["0x1", "0x1"]),
                             ("comparison_bound", {"kind": "design-5"}), ("verdict", "PASS")):
            changed = deepcopy(receipt)
            changed[field] = value
            variants.append(changed)
        changed = deepcopy(receipt)
        changed["arms"]["before"]["source"]["sha256"] = "0" * 64
        variants.append(changed)
        changed = deepcopy(receipt)
        changed["arms"]["before"]["observed_call_site"] = "0" * 64
        variants.append(changed)
        changed = deepcopy(receipt)
        changed["arms"]["after"]["outputs"][0]["value_sha256"] = "0" * 64
        variants.append(changed)
        changed = deepcopy(receipt)
        changed["arms"]["before"]["refinement_level"] = 3
        variants.append(changed)
        changed = deepcopy(receipt)
        changed["arms"]["before"]["outputs"][0]["history"]["trajectory_id"] = "0" * 64
        variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed.keys()):
                self.assertEqual(P.validate_receipt(changed, context)["verdict"], "FAIL")

    def test_receipt_is_closed_and_arbitrary_sidecar_is_not_evidence(self):
        context = self.context()
        receipt = P.emit_receipt("W.wall-normal", context)
        receipt["producer_observation"] = {"self_certified": True}
        self.assertEqual(P.validate_receipt(receipt, context)["verdict"], "FAIL")

    def test_no_producers_does_not_claim_other_family_coverage(self):
        self.pins = {arm: {} for arm in self.manifests}
        self.raw = {arm: {} for arm in self.manifests}
        report = self.report()
        self.assertEqual(report["verdict"], "NOT_APPLICABLE")
        self.assertEqual(report["mandatory_slots"], [])
        self.assertIn("no exhaustive", report["scope"])

    def test_lazy_records_are_consumed_once_and_only_compact_references_retained(self):
        rows = {arm: LazyRows(self.records[arm]["mesh"]) for arm in self.manifests}
        context = P.Context(self.manifests, self.pins, self.raw, rows, self.pairs)
        self.assertEqual([row.reads for row in rows.values()], [1, 1])
        self.assertNotIn("raw", context.records["before"]["mesh"])
        self.assertNotIn("record", context.records["before"]["mesh"])
        self.assertNotIn("cells", str(context.records))
        self.assertIsNotNone(P.emit_receipt("E.pose-operator-error", context))
        self.assertEqual([row.reads for row in rows.values()], [1, 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
