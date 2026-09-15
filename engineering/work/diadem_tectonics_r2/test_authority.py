"""Synthetic byte fixtures exercise closure; no historical producer executes."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("authority_under_test", Path(__file__).with_name("authority.py"))
authority = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(authority)


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="diadem_authority_synthetic_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package, self.evidence = self.root / "r1", self.root / "c1c"
        self.package.mkdir()
        self.evidence.mkdir()
        for name, (folder, _) in authority.SOURCE_ROLES.items():
            path = self.evidence / folder / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(("SYNTHETIC TEST ONLY " + name).encode())
        for name in authority.EXTRA_OUTPUTS:
            path = self.evidence / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(("SYNTHETIC TEST ONLY " + name).encode())
        self.old_audit = self.root / authority.HISTORY_INPUTS[3]
        self.old_audit.write_text(json.dumps({"overall_status": "PASS", "promotion_authorized": False}), encoding="utf-8")
        self.old_sha = self.hash(self.old_audit)
        for name in authority.HISTORY_INPUTS:
            if name != self.old_audit.name:
                (self.package / name).write_bytes(("SYNTHETIC HISTORY INPUT " + name).encode())
        inputs = [{"path": name, "sha256": self.hash(self.old_audit if name == self.old_audit.name else self.package / name)} for name in authority.HISTORY_INPUTS]
        inputs += [{"path": name, "sha256": "1" * 64} for name in authority.OTHER_INPUTS]
        self.provenance = {
            "builder": {"path": "build_checkpoint1c_constraint_atlas.py", "sha256": self.source_hash("build_checkpoint1c_constraint_atlas.py")},
            "inputs": inputs, "outputs": [{"path": name, "sha256": self.source_hash(name)} for name in authority.PROVENANCE_OUTPUTS]}
        self.save(authority.PROVENANCE, self.provenance)
        self.audit = {"overall_status": "PASS", "scientific_validation_status": "PASS", "blocking_codes": [],
                      "audited_artifact_hashes": {name: self.source_hash(name) for name in authority.AUDITED_NAMES},
                      "metrics": {"audited_hashes": {name: self.source_hash(name) for name in authority.AUDITED_NAMES}}}
        self.save(authority.AUDIT, self.audit)
        self.acceptance = {
            "record_id": "synthetic:acceptance", "checkpoint_id": "CHECKPOINT1C", "accepted_by": "SYNTHETIC TEST ACTOR",
            "decision": "ACCEPTED", "recorded_utc": "SYNTHETIC TIMESTAMP",
            "accepted_product": {"product_class": authority.PRODUCT_CLASS,
                                 "accepted_manifest_sha256_before_status_promotion": authority.OLD_MANIFEST_SHA,
                                 "atlas_provenance_sha256": self.hash(self.evidence / authority.PROVENANCE),
                                 "independent_adversarial_audit_sha256": self.hash(self.evidence / authority.AUDIT),
                                 "independent_scientific_validation_status": "PASS"},
            "authorization": {"next_checkpoint": "CHECKPOINT2", "macro_topography_stage_status": "ELIGIBLE", "topography_work_started_by_this_record": False},
            "scope_limits": {"three_dimensional_framework_status": "DEFERRED", "categorical_reference_realization_status": "REVIEW_ONLY",
                             "detailed_topography_stage_status": "BLOCKED", "hydrology_stage_status": "BLOCKED",
                             "final_outcrop_status": "DEFERRED_UNTIL_TOPOGRAPHY_AND_EROSION", "terrain_generated": False, "hydrology_generated": False}}
        self.save(authority.ACCEPTANCE, self.acceptance)
        self.status = {**authority.SCOPE_STATUSES, "terrain_generated": False, "hydrology_generated": False,
                       "checkpoint2_work_started": False, "package_old_3d_or_section_artifacts": False,
                       "acceptance_record_id": self.acceptance["record_id"], "acceptance_record_sha256": self.hash(self.evidence / authority.ACCEPTANCE),
                       "accepted_manifest_sha256_before_status_promotion": authority.OLD_MANIFEST_SHA}
        self.save(authority.STATUS, self.status)
        sources = [{"source_path": name, "package_path": f"{folder}/{name}", "role": role, "authority_status": "SYNTHETIC TEST ONLY",
                    "sha256": self.source_hash(name), "bytes": (self.evidence / folder / name).stat().st_size}
                   for name, (folder, role) in authority.SOURCE_ROLES.items()]
        outputs = [{"path": row["package_path"], "sha256": row["sha256"], "bytes": row["bytes"]} for row in sources]
        outputs += [{"path": name, "sha256": self.hash(self.evidence / name), "bytes": (self.evidence / name).stat().st_size} for name in sorted(authority.EXTRA_OUTPUTS)]
        self.manifest = {
            **authority.SCOPE_STATUSES, "product_class": authority.PRODUCT_CLASS, "authoritative_scope": authority.SCOPE,
            "coordinate_system": copy.deepcopy(authority.COORDINATES), "source_files": sources, "output_files": outputs,
            "output_file_count": 28,
            "independent_audit_binding": {"present": True, "status": "PASS", "current_hash_binding_required_for_pass": True,
                                          "audited_authoritative_source_names": list(authority.AUDITED_NAMES[:9])},
            "user_acceptance_binding": {
                **{key: self.acceptance[key] for key in ("record_id", "accepted_by", "decision", "recorded_utc")},
                "record_path": authority.ACCEPTANCE, "record_sha256": self.hash(self.evidence / authority.ACCEPTANCE),
                "accepted_manifest_sha256_before_status_promotion": authority.OLD_MANIFEST_SHA,
                "checkpoint2_eligible": True, "checkpoint2_work_started": False}}
        self.refresh_manifest()

    @staticmethod
    def hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def source_hash(self, name):
        return self.hash(self.evidence / authority.SOURCE_ROLES[name][0] / name)

    def save(self, relative, value):
        (self.evidence / relative).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")

    def refresh_manifest(self):
        self.save(authority.MANIFEST, self.manifest)
        self.pins = {name: self.hash(self.evidence / name) for name in authority.CONTROL_PINS}

    def run_scope(self):
        return authority._recover(self.package, self.evidence, self.pins, self.old_audit, self.old_sha)

    def test_pass_is_only_scoped_evidence_with_explicit_frame_and_split_parent(self):
        result = self.run_scope()
        self.assertEqual(result["status"], "PASS_EVIDENCE_CLOSURE")
        self.assertEqual(result["verified_output_file_count"], 28)
        self.assertEqual(result["verified_source_file_count"], 24)
        self.assertEqual(len(result["verified_files"]), 34)
        for key in ("category_complete", "production_authorized", "history_a_wholesale_acceptance_established", "fresh_scientific_or_visual_audit_performed", "downstream_generation_performed"):
            self.assertIs(result[key], False)
        self.assertEqual(result["plate_identity"], "NOT_ESTABLISHED_BY_THIS_EVIDENCE")
        self.assertEqual(result["snapshot_motion"], "NOT_ESTABLISHED_BY_THIS_EVIDENCE")
        self.assertFalse(result["pre_promotion_manifest"]["historical_bytes_rehashed"])
        frame = result["coordinate_relationship"]
        self.assertEqual(frame["c1c"]["shape_rows_columns"], [1650, 1950])
        self.assertEqual(frame["history_a"]["shape_rows_columns"], [1651, 1951])
        self.assertFalse(frame["sampling_equivalence"])
        self.assertFalse(frame["resampling_performed"])
        self.assertEqual([v["logical_name"] for v in result["history_a_bindings"]], list(authority.HISTORY_INPUTS))
        self.assertEqual(result["history_a_bindings"][3]["path"], str(self.old_audit))
        self.assertFalse((self.package / self.old_audit.name).exists())
        self.assertEqual(len(result["other_provenance_inputs_not_rehashed_by_this_scope"]), 3)

    def test_public_defaults_fixed_and_unoverridable(self):
        with patch.object(authority, "_recover", return_value={}) as called:
            authority.recovered_scope(self.package)
        called.assert_called_once_with(self.package, authority.C1C_ROOT, authority.CONTROL_PINS,
                                       authority.LEGACY / authority.HISTORY_INPUTS[3], authority.HISTORY_AUDIT_SHA)
        with self.assertRaises(TypeError):
            authority.CONTROL_PINS[authority.MANIFEST] = "0" * 64
        with self.assertRaises(TypeError):
            authority.recovered_scope(self.package, control_pins=self.pins)

    def test_read_only_repeatable(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self.run_scope(), self.run_scope())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_path_escape_alias_device_and_absolute_rejected(self):
        for value in ("../outside", "/outside", "C:/outside", "//server/share", "x\\y", "x//y", "x/./y", "NUL.txt", "x./y", "x /y", "x\x00y"):
            with self.subTest(path=value), self.assertRaises(authority.AuthorityError):
                authority._relative(value)

    def test_duplicate_and_case_alias_output_paths_fail(self):
        self.manifest["output_files"].append(copy.deepcopy(self.manifest["output_files"][0]))
        self.refresh_manifest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()
        self.manifest["output_files"][-1]["path"] = self.manifest["output_files"][0]["path"].upper()
        self.refresh_manifest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_missing_output_or_source_role_is_rejected(self):
        for key in ("output_files", "source_files"):
            with self.subTest(key=key):
                removed = self.manifest[key].pop()
                self.refresh_manifest()
                with self.assertRaises(authority.AuthorityError):
                    self.run_scope()
                self.manifest[key].append(removed)

    def test_changed_file_and_missing_file_fail(self):
        path = self.evidence / self.manifest["output_files"][0]["path"]
        path.write_bytes(b"changed")
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()
        path.unlink()
        with self.assertRaises(OSError):
            self.run_scope()

    def test_changed_parent_and_historical_audit_fail(self):
        path = self.package / authority.HISTORY_INPUTS[0]
        original = path.read_bytes()
        path.write_bytes(b"wrong historical vector")
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()
        path.write_bytes(original)
        self.old_audit.write_bytes(b"fresh reconstructed audit is not a substitute")
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_manifest_hardpin_cannot_self_repin(self):
        self.manifest["user_acceptance_status"] = "ACCEPTED_BY_SOMEBODY_ELSE"
        self.save(authority.MANIFEST, self.manifest)
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_source_role_mismatch(self):
        self.manifest["source_files"][0]["role"] = "tectonic_plate_authority"
        self.refresh_manifest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_size_type_and_source_output_size_disagreement(self):
        self.manifest["output_files"][0]["bytes"] = True
        self.refresh_manifest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()
        self.manifest["output_files"][0]["bytes"] = self.manifest["source_files"][0]["bytes"]
        self.manifest["source_files"][0]["bytes"] += 1
        self.refresh_manifest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_bool_int_status_not_equal(self):
        self.manifest["user_acceptance_binding"]["checkpoint2_work_started"] = 0
        self.refresh_manifest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_acceptance_pre_promotion_link_and_record_path_mismatch(self):
        for key, value in (("accepted_manifest_sha256_before_status_promotion", "a" * 64), ("record_path", "review/other.json")):
            original = self.manifest["user_acceptance_binding"][key]
            self.manifest["user_acceptance_binding"][key] = value
            self.refresh_manifest()
            with self.subTest(key=key), self.assertRaises(authority.AuthorityError):
                self.run_scope()
            self.manifest["user_acceptance_binding"][key] = original

    def test_frame_change_fails(self):
        self.manifest["coordinate_system"]["shape_rows_columns"] = [1651, 1951]
        self.refresh_manifest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_audit_binding_role_order_mismatch(self):
        self.manifest["independent_audit_binding"]["audited_authoritative_source_names"].reverse()
        self.refresh_manifest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_bad_hash_and_duplicate_control_json(self):
        self.pins[authority.MANIFEST] = "0" * 63
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()
        raw = b'{"status":"one","status":"two"}'
        (self.evidence / authority.MANIFEST).write_bytes(raw)
        self.pins[authority.MANIFEST] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(authority.AuthorityError):
            self.run_scope()

    def test_provenance_pin_duplicates_fail(self):
        with self.assertRaises(authority.AuthorityError):
            authority._named_pins([{"path": "one", "sha256": "0" * 64}] * 2)

    def test_end_rehash_detects_late_mutation(self):
        original = authority._identity
        target = self.package / authority.HISTORY_INPUTS[0]
        calls = 0

        def changed(path):
            nonlocal calls
            value = original(path)
            if Path(path) == target:
                calls += 1
                if calls == 2:
                    value["sha256"] = "0" * 64
            return value

        with patch.object(authority, "_identity", side_effect=changed):
            with self.assertRaises(authority.AuthorityError):
                self.run_scope()

    def test_reparse_input_rejected_without_following_it(self):
        original = Path.lstat
        target = self.package

        def reparse(path):
            value = original(path)
            if path == target:
                class Info:
                    st_mode = value.st_mode
                    st_file_attributes = 0x400
                return Info()
            return value

        with patch.object(Path, "lstat", reparse):
            with self.assertRaises(authority.AuthorityError):
                self.run_scope()


if __name__ == "__main__":
    unittest.main()
