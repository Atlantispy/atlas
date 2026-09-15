"""Synthetic adversarial tests for the NEW reconstructed auditor; no producer execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import audit


def fixture():
    shape = (3, 4)
    mask = np.zeros(shape, bool)
    mask[1, 1:3] = True
    checkpoint = {
        "coordinate_reference": {"public_frame_height": {"value": 2}, "public_frame_width": {"value": 3},
                                 "horizontal_unit": "km", "x_direction": "east", "y_direction": "south"},
        "peak_anchors": {"clockwise_order_from_north_west_gate_flank": ["One", "Two"],
                         "anchors": [{"haus": "One", "x": 1., "y": 1.}, {"haus": "Two", "x": 2., "y": 1.}]},
    }
    contract = {"required_events": {"a": ["E0", "E1", "E2", "E3A", "E5", "E6", "E7"]},
                "forbidden_downstream_tokens": ["river", "final_elevation"],
                "forbidden_lineage_tokens": ["q", "ellipse", "annular_distance"],
                "fault_block_raster_contract": {"outside_sentinel": 0},
                "hard_thresholds": {"reconstruction_tolerance": 1e-6}}
    arrays = {"x_km": np.arange(4, dtype=float), "y_km": np.arange(3, dtype=float),
              "approved_peak_reference_names": np.array(["One", "Two"]),
              "approved_peak_reference_xy_km": np.array([[1., 1.], [2., 1.]]),
              "approved_peak_reference_uncertainty_km": np.array([30., 30.]),
              "annular_coordinate_elevation_contribution_m": np.zeros(shape),
              "structural_model_domain_mask": mask}
    features = []
    for name, (layer, id_key) in audit.ID_LAYERS.items():
        arrays[name] = mask.astype(np.int16)
        features.append({"properties": {"layer": layer, id_key: "ID-" + name}})
    for name in audit.CONTRIBUTIONS:
        arrays[name] = np.full(shape, .25)
    arrays["relative_structural_potential"] = np.ones(shape)
    nodes = []
    for name in arrays:
        if name in audit.REFERENCE_ARRAYS:
            continue
        node = {"field": name, "operation": "derive from finite features", "parents": ["vector_features"],
                "feature_ids": ["ID-fault_block_id"]}
        if name in audit.ID_LAYERS:
            node["categorical_codebook"] = {"1": "ID-" + name}
        if name == "relative_structural_potential":
            node["parents"] = list(audit.CONTRIBUTIONS)
        nodes.append(node)
    lineage = {"schema_version": "1.0-review", "history": "A", "nodes": nodes,
               "array_hashes": hashes(arrays), "reconstruction": {
                   "total_array": "relative_structural_potential", "contribution_arrays": list(audit.CONTRIBUTIONS),
                   "tolerance": 1e-9}}
    events = {"schema_version": "1.0-review", "history": "A", "events": [
        {"event_id": event, "name": event, "structural_expression": "finite structure"}
        for event in contract["required_events"]["a"]]}
    return arrays, checkpoint, contract, features, lineage, events


def hashes(arrays):
    return {key: hashlib.sha256(audit.array_reader._array_bytes(value)).hexdigest() for key, value in arrays.items()}


def nodes(lineage):
    return {node["field"]: node for node in lineage["nodes"]}


class NumericAuditTests(unittest.TestCase):
    def setUp(self):
        self.arrays, self.checkpoint, self.contract, self.features, self.lineage, self.events = fixture()

    def raster(self):
        return audit._raster_checks(self.arrays, self.checkpoint, self.contract, self.features, self.lineage)

    def lineage_check(self):
        return audit._lineage_check(self.arrays, self.lineage, self.features, self.contract)

    def test_synthetic_valid_checks(self):
        self.assertEqual([r["status"] for r in self.raster()], ["PASS", "PASS"])
        self.assertEqual(self.lineage_check()["status"], "PASS")
        self.assertEqual(audit._event_check(self.events, self.contract)["status"], "PASS")

    def test_event_order_missing_duplicate_history(self):
        for kind in ("order", "missing", "duplicate", "history", "description"):
            with self.subTest(kind=kind):
                altered = deepcopy(self.events)
                if kind == "order": altered["events"].reverse()
                if kind == "missing": altered["events"].pop()
                if kind == "duplicate": altered["events"].append(altered["events"][0])
                if kind == "history": altered["history"] = "B"
                if kind == "description": altered["events"][0]["structural_expression"] = ""
                self.assertEqual(audit._event_check(altered, self.contract)["status"], "FAIL")

    def test_mask_and_assignment_mutations(self):
        for kind in ("dtype", "all", "empty", "outside", "inside"):
            with self.subTest(kind=kind):
                self.setUp()
                mask = self.arrays["structural_model_domain_mask"]
                if kind == "dtype": self.arrays["structural_model_domain_mask"] = mask.astype(int)
                if kind == "all": mask[:] = True
                if kind == "empty": mask[:] = False
                if kind == "outside": self.arrays["fault_block_id"][0, 0] = 1
                if kind == "inside": self.arrays["fault_block_id"][1, 1] = 0
                self.assertEqual(self.raster()[1]["status"], "FAIL")

    def test_codebook_numeric_vector_ids(self):
        for kind in ("unseen", "vector", "leading_zero", "negative", "float"):
            with self.subTest(kind=kind):
                self.setUp()
                field = "fault_block_id"
                book = nodes(self.lineage)[field]["categorical_codebook"]
                if kind == "unseen": self.arrays[field][1, 1] = 2
                if kind == "vector": book["1"] = "UNKNOWN"
                if kind == "leading_zero": book["01"] = book.pop("1")
                if kind == "negative": self.arrays[field][1, 1] = -1
                if kind == "float": self.arrays[field] = self.arrays[field].astype(float)
                self.assertEqual(self.raster()[1]["status"], "FAIL")

    def test_continuous_schema_and_references(self):
        for kind in ("nan", "integer", "shape", "axis", "frame", "names", "anchor", "uncertainty", "annular"):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == "nan": self.arrays[audit.CONTRIBUTIONS[0]][0, 0] = np.nan
                if kind == "integer": self.arrays[audit.CONTRIBUTIONS[0]] = np.zeros((3, 4), dtype=int)
                if kind == "shape": self.arrays[audit.CONTRIBUTIONS[0]] = np.zeros((1, 4))
                if kind == "axis": self.arrays["x_km"][0] = 0.1
                if kind == "frame": self.checkpoint["coordinate_reference"]["y_direction"] = "north"
                if kind == "names": self.arrays["approved_peak_reference_names"] = np.array(["Two", "One"])
                if kind == "anchor": self.arrays["approved_peak_reference_xy_km"][0, 0] = 0.
                if kind == "uncertainty": self.arrays["approved_peak_reference_uncertainty_km"][0] = 29.
                if kind == "annular": self.arrays["annular_coordinate_elevation_contribution_m"][0, 0] = 1.
                self.assertEqual(self.raster()[0]["status"], "FAIL")

    def test_lineage_identity_and_dag(self):
        for kind in ("missing", "duplicate", "cycle", "parent", "feature", "orphan", "hash", "operation", "forbidden"):
            with self.subTest(kind=kind):
                self.setUp()
                node = nodes(self.lineage)[audit.CONTRIBUTIONS[0]]
                if kind == "missing": self.lineage["nodes"].pop(0)
                if kind == "duplicate": self.lineage["nodes"].append(deepcopy(node))
                if kind == "cycle": node["parents"] = ["relative_structural_potential"]
                if kind == "parent": node["parents"] = ["unknown"]
                if kind == "feature": node["feature_ids"] = ["unknown"]
                if kind == "orphan": node["feature_ids"] = []
                if kind == "hash": self.lineage["array_hashes"]["x_km"] = "0" * 64
                if kind == "operation": node["operation"] = ""
                if kind == "forbidden": node["operation"] = "derive using annular_distance"
                self.assertEqual(self.lineage_check()["status"], "FAIL")

    def test_reconstruction_residual_and_no_tolerance_relaxation(self):
        for kind in ("residual", "tolerance", "order", "parents", "shape", "nan"):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == "residual": self.arrays["relative_structural_potential"][0, 0] += 1e-5
                if kind == "tolerance": self.lineage["reconstruction"]["tolerance"] = 1e-5
                if kind == "order": self.lineage["reconstruction"]["contribution_arrays"].reverse()
                if kind == "parents": nodes(self.lineage)["relative_structural_potential"]["parents"] = ["vector_features"]
                if kind == "shape": self.arrays[audit.CONTRIBUTIONS[0]] = np.zeros((1, 4))
                if kind == "nan": self.arrays[audit.CONTRIBUTIONS[0]][0, 0] = np.nan
                self.lineage["array_hashes"] = hashes(self.arrays)
                self.assertEqual(self.lineage_check()["status"], "FAIL")

    def test_forbidden_tokens_do_not_match_arbitrary_letters(self):
        self.assertEqual(audit._forbidden("sequence and equivalent", ["q"]), [])
        self.assertEqual(audit._forbidden("use_q", ["q"]), ["q"])


class MetadataAndSummaryTests(unittest.TestCase):
    def test_review_readiness_never_means_acceptance(self):
        checks = {code: audit._check(code, "PASS", "Synthetic check") for code in audit.CODES}
        rows, summary = audit._aggregate(checks)
        self.assertEqual(len(rows), 24)
        self.assertEqual(summary["review_readiness"], "PASS")
        self.assertFalse(summary["production_authorized"])
        self.assertFalse(summary["category_complete"])
        self.assertEqual(summary["checkpoint_acceptance"], "NOT_ESTABLISHED_BY_THIS_AUDIT")

    def test_visual_pending_blocks_and_any_failure_fails(self):
        for status in ("BLOCKED", "FAIL"):
            checks = {code: audit._check(code, "PASS", "Synthetic check") for code in audit.CODES}
            checks["COMPLETE_VISUAL_EVIDENCE"]["status"] = status
            _, summary = audit._aggregate(checks)
            self.assertEqual(summary["review_readiness"], status)
            self.assertEqual(summary["overall_status"], status)

    def test_missing_code_and_unknown_status_rejected(self):
        for kind in ("missing", "status", "identity"):
            checks = {code: audit._check(code, "PASS", "Synthetic check") for code in audit.CODES}
            if kind == "missing": checks.pop(audit.CODES[0])
            if kind == "status": checks[audit.CODES[0]]["status"] = "UNKNOWN"
            if kind == "identity": checks[audit.CODES[0]]["code"] = "OTHER"
            with self.assertRaises(ValueError): audit._aggregate(checks)

    def test_preserved_pending_and_shared_metadata(self):
        shared = {"schema_version": "1.0-review", "checkpoint": "checkpoint-1-structural-geology",
                  "status": "REVIEW_ONLY_NOT_ACCEPTED", "authority": {}, "generator_sources": [],
                  "histories": {"A": {"status": "selected_under_review", "artifacts": {}},
                                "B": {"status": "not_selected_before_implementation", "artifacts": {}}},
                  "production_unchanged": True, "master_ledger_unchanged": True}
        review = {"schema_version": "1.0-review", "history": "A", "status": "PENDING",
                  "reviewer_role": "pending_independent", "items": [{"role": "plan", "status": "PENDING",
                    "notes": "Complete evidence rendered; awaiting independent adversarial review."}]}
        self.assertEqual(audit._metadata_errors(shared, review, ["plan"]), [])
        for kind in ("promotion", "boolean_type", "history", "review", "reviewer"):
            altered, changed = deepcopy(shared), deepcopy(review)
            if kind == "promotion": altered["production_authorized"] = True
            if kind == "boolean_type": altered["production_unchanged"] = 1
            if kind == "history": altered["histories"]["B"]["status"] = "approved"
            if kind == "review": changed["status"] = "PASS"
            if kind == "reviewer": changed["reviewer_role"] = "historical_independent"
            self.assertTrue(audit._metadata_errors(altered, changed, ["plan"]))

    def test_unsafe_package_is_fail_closed_without_source_reads(self):
        with patch.object(audit.sources, "inspect_sources") as source:
            result = audit.audit_package(Path("relative"), Path("relative"))
        source.assert_not_called()
        self.assertEqual(len(result["checks"]), 24)
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertFalse(result["production_authorized"])

    def test_source_unavailable_is_blocked_and_never_generated(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            package = root / "sandbox" / audit.sources.REBUILD
            package.mkdir(parents=True)
            before = {"review_replay_source_gate_passed": False, "files": [], "issues": ["Missing original"]}
            with patch.object(audit.sources, "inspect_sources", return_value=before):
                result = audit.audit_package(package, root)
        self.assertEqual(result["overall_status"], "BLOCKED")
        self.assertEqual(result["summary"]["pass_count"], 0)
        self.assertFalse(result["production_authorized"])


class FreshVisualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name)
        self.roles = ["role_" + str(i) for i in range(11)]
        self.contract = {"required_visual_roles": self.roles}
        self.manifest = {"artifacts": []}
        for path in (self.package / Path(audit.sources.CONTRACT).name, self.package / Path(audit.sources.SHARED).name):
            path.write_text("{}", encoding="utf-8")
        items = []
        for role in self.roles:
            name = f"{audit.PREFIX}{role.replace('_', '-')}-review-only.png"
            path = self.package / name
            path.write_bytes(role.encode())  # Identity tests; image interpretation is independent.
            digest = audit._identity(path)["sha256"]
            self.manifest["artifacts"].append({"sha256": digest})
            items.append({"role": role, "path": name, "sha256": digest, "status": "PASS", "notes": "Actually inspected fixture."})
        self.document = {"schema": "diadem.tectonics.independent-visual-review.v1", "history": "A", "status": "PASS",
                         "reviewer_role": "independent", "review_kind": "NEW_INDEPENDENT_ENGINEERING_VISUAL_REVIEW",
                         "contract_sha256": audit._identity(self.package / Path(audit.sources.CONTRACT).name)["sha256"],
                         "package_manifest_sha256": audit._identity(self.package / Path(audit.sources.SHARED).name)["sha256"],
                         "production_authorized": False, "items": items}
        self.path = self.package / "new-independent-review.json"

    def check(self):
        self.path.write_text(json.dumps(self.document), encoding="utf-8")
        return audit._visual_check(self.path, self.package, self.contract, self.manifest)

    def test_fresh_complete_record(self):
        self.assertEqual(self.check()["status"], "PASS")

    def test_missing_is_blocked(self):
        self.assertEqual(audit._visual_check(None, self.package, self.contract, self.manifest)["status"], "BLOCKED")

    def test_visual_binding_and_status_mutations(self):
        original = deepcopy(self.document)
        for kind in ("history", "historical", "promotion", "extra", "missing", "order", "path", "hash", "notes", "fail", "contract"):
            with self.subTest(kind=kind):
                self.document = deepcopy(original)
                if kind == "history": self.document["history"] = "B"
                if kind == "historical": self.document["review_kind"] = "HISTORICAL"
                if kind == "promotion": self.document["production_authorized"] = True
                if kind == "extra": self.document["canon_approved"] = True
                if kind == "missing": self.document["items"].pop()
                if kind == "order": self.document["items"].reverse()
                if kind == "path": self.document["items"][0]["path"] = "../other.png"
                if kind == "hash": self.document["items"][0]["sha256"] = "0" * 64
                if kind == "notes": self.document["items"][0]["notes"] = " "
                if kind == "fail": self.document["items"][0]["status"] = "FAIL"
                if kind == "contract": self.document["contract_sha256"] = "0" * 64
                self.assertEqual(self.check()["status"], "FAIL")

    def test_image_mutation_detected(self):
        self.check()
        (self.package / self.document["items"][0]["path"]).write_bytes(b"changed")
        self.assertEqual(self.check()["status"], "FAIL")

    def test_strict_json_duplicate_and_nonfinite(self):
        for raw in ('{"status": "PASS", "status": "PASS"}', '{"x": NaN}', '{"x": 1e999}'):
            self.path.write_text(raw, encoding="utf-8")
            self.assertEqual(audit._visual_check(self.path, self.package, self.contract, self.manifest)["status"], "FAIL")


class BoundedDecoderTests(unittest.TestCase):
    def test_small_numeric_npz_decodes_all_fields(self):
        arrays, *_ = fixture()
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "fixture.npz"
            np.savez_compressed(path, **arrays)
            result = audit._load_arrays(path)
        self.assertEqual(set(result), set(arrays))
        for key in arrays:
            self.assertEqual(result[key].dtype, arrays[key].dtype)
            np.testing.assert_array_equal(result[key], arrays[key])

    def test_total_decoded_input_bound(self):
        arrays, *_ = fixture()
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "fixture.npz"
            np.savez_compressed(path, **arrays)
            with patch.object(audit, "MAX_ARRAY_TOTAL_BYTES", 1), self.assertRaises(ValueError):
                audit._load_arrays(path)

    def test_object_payload_never_unpickled(self):
        arrays, *_ = fixture()
        arrays["approved_peak_reference_names"] = np.array(["One", "Two"], dtype=object)
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "fixture.npz"
            np.savez_compressed(path, **arrays)
            with self.assertRaises((ValueError, RuntimeError)):
                audit._load_arrays(path)


if __name__ == "__main__":
    unittest.main()
