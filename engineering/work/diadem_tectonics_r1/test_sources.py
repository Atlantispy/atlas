from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import sources as source


class SourceTests(unittest.TestCase):
    """Small synthetic authenticated closures; never execute a producer."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pins = {}
        self.patch("BOOTSTRAP_PINS", self.pins)
        master = b"exact historical master fixture"
        self.patch("MASTER_SHA256", hashlib.sha256(master).hexdigest())
        self.write(source.MASTER_ARCHIVE, master)
        self.write(source.MASTER, b"different current master; must never substitute")
        self.write_json(source.ANCHOR, {"fixture": "anchor evidence"})
        self.patch("ANCHOR_SHA256", self.digest(source.ANCHOR))
        anchors = [{"haus": name, "x": float(i), "y": float(i * 2), "unit": "km",
                    "status": "approved_macro_anchor"} for i, name in enumerate(source.ANCHOR_ORDER)]
        coordinate_hash = hashlib.sha256(b"".join(struct.pack("<dd", a["x"], a["y"]) for a in anchors)).hexdigest()
        self.patch("COORDINATE_SHA256", coordinate_hash)
        for relative in source.SOURCE_PATHS:
            self.write(relative, b"raise AssertionError('Historical producer must not be imported')\n")
        for relative in source.ARTIFACT_PATHS.values():
            self.write(relative, b"{}" if relative.endswith((".json", ".geojson")) else b"opaque numeric fixture")
        frozen = []
        for relative, role, unchanged in source.FROZEN_IDENTITIES:
            actual = source.MASTER_ARCHIVE if relative == source.MASTER else relative
            if not (self.root / actual).exists():
                self.write(actual, b"{}" if actual.endswith(".json") else b"frozen fixture")
            frozen.append({"path": relative, "role": role,
                           "must_remain_unchanged_until_checkpoint1_review": unchanged,
                           "sha256": self.digest(actual)})
        self.checkpoint = {
            "schema_version": "1.0.0",
            "checkpoint": {"id": "checkpoint-0", "name": "frozen-inputs", "status": "accepted",
                           "promotion_authorized": False, "next_checkpoint": "checkpoint-1-structural-geology"},
            "authority": {"master_ledger": {"path": source.MASTER, "sha256": source.MASTER_SHA256, "version": "0.31"}},
            "file_freeze_snapshot": {"hash_algorithm": "sha256", "files": frozen},
            "peak_anchors": {
                "status": "approved_transfer_zone_resegmentation_macro_reference",
                "clockwise_order_from_north_west_gate_flank": source.ANCHOR_ORDER,
                "anchors": anchors,
                "decision_provenance": {"ordered_coordinate_sha256": coordinate_hash,
                                        "source_review_sha256": source.ANCHOR_SHA256}},
        }
        self.write_json(source.CHECKPOINT0, self.checkpoint)
        self.pins[source.CHECKPOINT0] = self.digest(source.CHECKPOINT0)
        self.contract = {
            "schema_version": "1.0.0-review", "status": "active_fail_closed_audit_contract",
            "checkpoint": "checkpoint-1-structural-geology", "production_authority": False,
            "selected_history": "a", "history_selection": {"approval_verbatim": "I choose A",
                      "history_b_status": "not_selected_before_implementation"},
            "authority": {"checkpoint0_manifest": {"path": source.CHECKPOINT0, "sha256": self.pins[source.CHECKPOINT0]},
                          "anchor_source_review": {"path": source.ANCHOR, "sha256": source.ANCHOR_SHA256},
                          "approved_coordinate_sha256": coordinate_hash},
            "required_visual_roles": source.VISUAL_ROLES,
        }
        self.write_json(source.CONTRACT, self.contract)
        self.visual = {"schema_version": "1.0-review", "history": "A",
                       "status": "COMPLETE_AWAITING_INDEPENDENT_REVIEW", "artifacts": []}
        for role in source.VISUAL_ROLES:
            relative = f"{source.REBUILD}/checkpoint1-history-a-{role.replace('_', '-')}-review-only.png"
            self.write(relative, b"opaque visual fixture")
            self.visual["artifacts"].append({"role": role, "path": relative, "sha256": self.digest(relative)})
        self.review = {"schema_version": "1.0-review", "history": "A", "status": "PASS",
                       "reviewer_role": "independent", "items": [{"role": r, "status": "PASS"} for r in source.VISUAL_ROLES]}
        self.write_json(source.ARTIFACT_PATHS["visual_manifest"], self.visual)
        self.write_json(source.ARTIFACT_PATHS["visual_review"], self.review)
        self.shared = {
            "schema_version": "1.0-review", "checkpoint": "checkpoint-1-structural-geology",
            "status": "REVIEW_ONLY_NOT_ACCEPTED", "production_unchanged": True, "master_ledger_unchanged": True,
            "authority": {"checkpoint0_manifest_sha256": self.pins[source.CHECKPOINT0],
                          "approved_coordinate_sha256": coordinate_hash,
                          "anchor_source_review_sha256": source.ANCHOR_SHA256,
                          "selected_history": "A", "selection_verbatim": "I choose A"},
            "generator_sources": [{"path": p, "sha256": self.digest(p)} for p in source.SOURCE_PATHS],
            "histories": {"A": {"status": "selected_under_review", "artifacts": {
                role: {"path": p, "sha256": self.digest(p)} for role, p in source.ARTIFACT_PATHS.items()}},
                "B": {"status": "not_selected_before_implementation", "artifacts": {}}},
        }
        self.audit = {
            "schema_version": "1.0.0-review", "audit": "checkpoint1-event-model-independent-fail-closed",
            "overall_status": "PASS", "promotion_authorized": False, "fail_closed": True,
            "histories_audited": ["a"],
            "contract": {"path": str(source.SOURCE_ROOT / source.CONTRACT), "sha256": self.digest(source.CONTRACT)},
            "checks": [{"code": c, "status": "PASS"} for c in source.AUDIT_CODES],
            "summary": {"pass_count": 24, "fail_count": 0, "blocking_codes": [],
                        "checkpoint2_status": "eligible_only_after_michael_checkpoint_acceptance"},
        }
        self.trust(source.SHARED, self.shared)
        self.trust(source.AUDIT, self.audit)

    def patch(self, name, value):
        patcher = patch.object(source, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def write_json(self, relative, value):
        self.write(relative, json.dumps(value).encode())

    def digest(self, relative):
        return hashlib.sha256((self.root / relative).read_bytes()).hexdigest()

    def trust(self, relative, value):
        """Test-only signing of synthetic documents, never a live source repin."""
        self.write_json(relative, value)
        digest = self.digest(relative)
        if relative in (source.SHARED, source.AUDIT, source.CHECKPOINT0):
            self.pins[relative] = digest
        if relative == source.CHECKPOINT0:
            self.shared["authority"]["checkpoint0_manifest_sha256"] = digest
            self.contract["authority"]["checkpoint0_manifest"]["sha256"] = digest
            self.trust(source.CONTRACT, self.contract)
        elif relative == source.CONTRACT:
            self.shared["generator_sources"][1]["sha256"] = digest
            self.audit["contract"]["sha256"] = digest
            self.trust(source.SHARED, self.shared)
            self.trust(source.AUDIT, self.audit)
        elif relative in source.ARTIFACT_PATHS.values():
            role = next(k for k, p in source.ARTIFACT_PATHS.items() if p == relative)
            self.shared["histories"]["A"]["artifacts"][role]["sha256"] = digest
            self.trust(source.SHARED, self.shared)

    def blocked(self):
        result = source.inspect_sources(self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["review_replay_source_gate_passed"])
        self.assertFalse(result["production_authority_established"])
        self.assertTrue(result["issues"])
        return result

    def test_complete_historical_only_gate(self):
        result = source.require_sources(self.root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["files"]), 35)
        self.assertFalse(result["production_authority_established"])
        self.assertFalse(result["current_canon_authority_established"])
        self.assertFalse(result["historical_audit_reexecuted"])
        self.assertEqual(result["fresh_scientific_tests_run"], 0)
        master = next(r for r in result["files"] if r["relative_path"] == source.MASTER)
        self.assertEqual(master["resolved_relative_path"], source.MASTER_ARCHIVE)
        self.assertEqual(master["expected_sha256"], master["actual_sha256"])

    def test_source_drift_blocks(self):
        self.write(source.SOURCE_PATHS[0], b"changed")
        self.blocked()
        with self.assertRaises(source.SourceGateError):
            source.require_sources(self.root)

    def test_missing_master_never_uses_current_master(self):
        self.write(source.MASTER, (self.root / source.MASTER_ARCHIVE).read_bytes())
        (self.root / source.MASTER_ARCHIVE).unlink()
        self.blocked()

    def test_changed_archived_master_blocks(self):
        self.write(source.MASTER_ARCHIVE, b"wrong version")
        self.blocked()

    def test_bootstrap_drift_blocks_without_parsing(self):
        self.write(source.SHARED, b"not json")
        self.blocked()

    def test_duplicate_json_rejected(self):
        self.write(source.SHARED, b'{"x":1,"x":2}')
        self.pins[source.SHARED] = self.digest(source.SHARED)
        with self.assertRaisesRegex(source.SourceGateError, "duplicate JSON"):
            source.inspect_sources(self.root)

    def test_nonfinite_and_overflow_json_rejected(self):
        for token in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(token=token):
                self.write(source.SHARED, ('{"x":' + token + '}').encode())
                self.pins[source.SHARED] = self.digest(source.SHARED)
                with self.assertRaises(source.SourceGateError):
                    source.inspect_sources(self.root)

    def test_malformed_digest_rejected(self):
        self.shared["generator_sources"][0]["sha256"] = "not-a-digest"
        self.trust(source.SHARED, self.shared)
        with self.assertRaisesRegex(source.SourceGateError, "SHA256"):
            source.inspect_sources(self.root)

    def test_no_sources_cannot_pass_vacuously(self):
        self.shared["generator_sources"] = []
        self.trust(source.SHARED, self.shared)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_no_artifacts_cannot_pass_vacuously(self):
        self.shared["histories"]["A"]["artifacts"] = {}
        self.trust(source.SHARED, self.shared)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_missing_frozen_identity_rejected(self):
        self.checkpoint["file_freeze_snapshot"]["files"].pop()
        self.trust(source.CHECKPOINT0, self.checkpoint)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_wrong_history_or_status_rejected(self):
        original = copy.deepcopy(self.shared)
        for key, value in (("status", "ACCEPTED"), ("production_unchanged", 1)):
            self.shared = copy.deepcopy(original)
            self.shared[key] = value
            self.trust(source.SHARED, self.shared)
            with self.subTest(key=key), self.assertRaises(source.SourceGateError):
                source.inspect_sources(self.root)
        self.shared = copy.deepcopy(original)
        self.shared["authority"]["selected_history"] = "B"
        self.trust(source.SHARED, self.shared)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_production_contract_and_integer_false_rejected(self):
        for value in (True, 0):
            self.contract["production_authority"] = value
            self.trust(source.CONTRACT, self.contract)
            with self.subTest(value=value), self.assertRaises(source.SourceGateError):
                source.inspect_sources(self.root)

    def test_no_or_failed_historical_tests_rejected(self):
        original = copy.deepcopy(self.audit)
        for checks in ([], [{"code": c, "status": "FAIL"} for c in source.AUDIT_CODES]):
            self.audit = copy.deepcopy(original)
            self.audit["checks"] = checks
            self.trust(source.AUDIT, self.audit)
            with self.assertRaises(source.SourceGateError):
                source.inspect_sources(self.root)

    def test_historical_promotion_claim_rejected(self):
        self.audit["promotion_authorized"] = True
        self.trust(source.AUDIT, self.audit)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_coordinate_drift_rejected_even_if_document_rehashed(self):
        self.checkpoint["peak_anchors"]["anchors"][0]["x"] += 0.01
        self.trust(source.CHECKPOINT0, self.checkpoint)
        with self.assertRaisesRegex(source.SourceGateError, "coordinate hash"):
            source.inspect_sources(self.root)

    def test_duplicate_anchor_identity_rejected(self):
        self.checkpoint["peak_anchors"]["anchors"][0] = self.checkpoint["peak_anchors"]["anchors"][1]
        self.trust(source.CHECKPOINT0, self.checkpoint)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_unsafe_paths_rejected(self):
        for path in ("../outside", "/outside", "C:/outside", "C:relative", "//?/C:/x", "//./pipe/x",
                     "\\\\?\\GLOBALROOT\\Device\\x", "a/../../x", "a\\..\\x", "a//b", "a/./b",
                     "a/b.", "a/b ", "NUL.txt", "a:stream", "a\x00b"):
            with self.subTest(path=path), self.assertRaises(source.SourceGateError):
                source._relative(path)

    def test_manifest_path_escape_rejected(self):
        self.shared["generator_sources"][0]["path"] = "../outside.py"
        self.trust(source.SHARED, self.shared)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_reparse_and_dangling_symlink_guard(self):
        for info in (SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0),
                     SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)):
            with patch.object(Path, "lstat", return_value=info), self.assertRaises(source.SourceGateError):
                source._no_links(self.root)

    def test_symlink_read_is_blocked_before_open(self):
        with patch.object(source, "_no_links", side_effect=source.SourceGateError("link")), patch.object(source.os, "open") as opened:
            self.blocked()
            opened.assert_not_called()

    def test_invalid_root_is_controlled(self):
        for root in ("relative", "//?/C:/x", self.root / "missing", None):
            result = source.inspect_sources(root)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(result["production_authority_established"])

    def test_missing_document_key_is_controlled(self):
        del self.shared["histories"]
        self.trust(source.SHARED, self.shared)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_visual_drift_and_pending_review_block(self):
        self.review["status"] = "PENDING"
        self.trust(source.ARTIFACT_PATHS["visual_review"], self.review)
        with self.assertRaises(source.SourceGateError):
            source.inspect_sources(self.root)

    def test_changed_during_read_blocks(self):
        count = 0
        def identity(_):
            nonlocal count
            count += 1
            return (1,) if count <= 3 else (2,)
        with patch.object(source, "_identity", side_effect=identity):
            self.blocked()

    def test_json_read_bound(self):
        with patch.object(source, "MAX_JSON_BYTES", 1):
            self.blocked()

    def test_windows_ctime_api_difference_is_not_ignored(self):
        values = dict(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_birthtime_ns=5)
        path_stat = SimpleNamespace(**values, st_ctime_ns=5)
        handle_stat = SimpleNamespace(**values, st_ctime_ns=6)
        with patch.object(source.os, "name", "nt"):
            self.assertEqual(source._identity(path_stat), source._identity(handle_stat))
            self.assertNotEqual(source._api_identity(path_stat), source._api_identity(handle_stat))

    def test_read_only_and_no_producer_import(self):
        before = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob("*") if p.is_file()}
        source.require_sources(self.root)
        after = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
