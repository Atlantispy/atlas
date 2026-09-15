"""Small synthetic fixtures only; no generated values are Diadem decisions."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("snapshot_under_test", Path(__file__).with_name("snapshot.py"))
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="diadem_snapshot_synthetic_")
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name)
        self.blocks = [f"A-B{i:02d}" for i in range(10, 0, -1)]
        self.faults = [f"SYNTHETIC-FAULT-{i:02d}" for i in range(44)]
        features = []
        for i, block_id in enumerate(self.blocks):
            features.append({"type": "Feature", "properties": {"layer": "structural_block", "block_id": block_id,
                             "relative_vertical_rank": i, "source_or_support": "SYNTHETIC TEST ONLY"},
                             "geometry": {"type": "Polygon", "coordinates": [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 0]]]}})
        for i, fault_id in enumerate(self.faults):
            features.append({"type": "Feature", "properties": {"layer": "fault_segment", "fault_id": fault_id,
                             "left_block_id": "A-B01", "right_block_id": "A-B02", "relative_throw_class": "major",
                             "relative_age_order": 7, "geometry_status": "candidate", "activity_state": "active"},
                             "geometry": {"type": "LineString", "coordinates": [[0, 10], [0, 0]] if i == 1 else [[0, 0], [10, 0]]}})
        self.vector = {"type": "FeatureCollection", "name": "SYNTHETIC TEST ONLY", "features": features}
        self.events = {"history": "A", "events": [{"event_id": "E7", "name": "SYNTHETIC present state"}]}
        self.lineage = {"history": "A", "nodes": [{"field": "SYNTHETIC", "operation": "not a Diadem input"}]}
        self.manifest = {"status": "REVIEW_ONLY_NOT_ACCEPTED", "authority": {"selected_history": "A"},
                         "histories": {"A": {"status": "selected_under_review", "artifacts": {}}}}
        self.save_package()

    def write(self, name, value):
        (self.package / name).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")

    def save_package(self):
        for role, value in (("faults_blocks", self.vector), ("events", self.events), ("lineage", self.lineage)):
            name = snapshot.FILES[role]
            self.write(name, value)
            self.manifest["histories"]["A"]["artifacts"][role] = {
                "path": "work/stage4-rebuild/" + name,
                "sha256": hashlib.sha256((self.package / name).read_bytes()).hexdigest()}
        self.write(snapshot.MANIFEST, self.manifest)

    def decisions(self):
        return {"schema_version": 1, "snapshot_id": "SYNTHETIC TEST SNAPSHOT NOT DIADEM",
                "snapshot_source_refs": ["synthetic"], "frame": snapshot.FRAME,
                "reference_frame": "SYNTHETIC fixed local reference", "frame_source_refs": ["synthetic"],
                "velocity_units": snapshot.UNITS, "source_status": "SYNTHETIC_TEST_ONLY",
                "source_refs": [{"id": "synthetic", "path": str(self.package / snapshot.MANIFEST),
                                 "sha256": hashlib.sha256((self.package / snapshot.MANIFEST).read_bytes()).hexdigest(),
                                 "status": "SYNTHETIC_TEST_ONLY", "locator": "synthetic fixture; not authority"}],
                "blocks": [], "faults": []}

    def block(self, block_id, vx, vy, plate=None):
        return {"block_id": block_id, "plate_id": plate,
                "plate_identity_source_refs": ["synthetic"] if plate is not None else [],
                "velocity": {"vx": vx, "vy": vy, "frame": snapshot.FRAME,
                             "reference_frame": "SYNTHETIC fixed local reference", "units": snapshot.UNITS,
                             "source_refs": ["synthetic"]}}

    def two_motions(self, left=(0, 0), right=(3, 4)):
        decisions = self.decisions()
        decisions["blocks"] = [self.block("A-B01", *left), self.block("A-B02", *right)]
        return decisions

    def run_snapshot(self, decisions=None):
        return snapshot.build_snapshot(self.package, decisions)

    def motion(self, result):
        return result["products"][snapshot.PRODUCT_NAMES[2]]

    def test_unknown_is_incomplete_not_zero_or_inferred_from_rank(self):
        result = self.run_snapshot()
        self.assertEqual(result["validation"]["status"], "INCOMPLETE")
        self.assertFalse(result["validation"]["production_authorized"])
        motion = self.motion(result)
        self.assertIsNone(motion["velocity_reference_frame"])
        for block in motion["blocks"]:
            self.assertIsNone(block["vx"])
            self.assertIsNone(block["vy"])
            self.assertIsNone(block["speed"])
        for fault in motion["faults"]:
            self.assertIsNone(fault["relative_velocity_right_minus_left"]["speed"])
            self.assertIsNone(fault["segments"][0]["right_normal_velocity"])

    def test_exact_product_inventory_and_source_feature_preservation(self):
        result = self.run_snapshot()
        self.assertEqual(tuple(result["products"]), snapshot.PRODUCT_NAMES)
        for key, offset, extra in ((snapshot.PRODUCT_NAMES[0], 0, "tectonic_crosswalk"),
                                   (snapshot.PRODUCT_NAMES[1], 10, "tectonic_relationship")):
            for index, feature in enumerate(result["products"][key]["features"]):
                original = copy.deepcopy(feature)
                del original["properties"][extra]
                self.assertEqual(original, self.vector["features"][offset + index])
        self.assertEqual([f["properties"]["block_id"] for f in result["products"][snapshot.PRODUCT_NAMES[0]]["features"]], self.blocks)
        self.assertEqual(self.motion(result)["retained_events"], self.events)
        self.assertEqual(self.motion(result)["retained_lineage"], self.lineage)

    def test_known_vector_speed_and_bearing(self):
        motion = self.motion(self.run_snapshot(self.two_motions()))
        block = next(v for v in motion["blocks"] if v["block_id"] == "A-B02")
        self.assertEqual(block["speed"], 5)
        self.assertAlmostEqual(block["bearing_clockwise_from_north_deg"], 143.13010235415598)

    def test_eastward_trace_right_normal_points_south(self):
        segment = self.motion(self.run_snapshot(self.two_motions()))["faults"][0]["segments"][0]
        self.assertEqual(segment["unit_tangent"], [1, 0])
        self.assertEqual(segment["unit_right_normal"], [0, 1])
        self.assertEqual(segment["tangential_velocity"], 3)
        self.assertEqual(segment["right_normal_velocity"], 4)
        self.assertEqual(segment["left_normal_velocity"], -4)

    def test_northward_trace_right_normal_points_east(self):
        segment = self.motion(self.run_snapshot(self.two_motions()))["faults"][1]["segments"][0]
        self.assertEqual(segment["unit_tangent"], [0, -1])
        self.assertEqual(segment["unit_right_normal"], [1, 0])
        self.assertEqual(segment["tangential_velocity"], -4)
        self.assertEqual(segment["right_normal_velocity"], 3)

    def test_relative_vector_right_minus_left(self):
        vector = self.motion(self.run_snapshot(self.two_motions((2, -3), (5, 1))))["faults"][0]["relative_velocity_right_minus_left"]
        self.assertEqual(vector["vx"], 3)
        self.assertEqual(vector["vy"], 4)
        self.assertEqual(vector["speed"], 5)

    def test_zero_known_velocity_has_zero_speed_null_bearing(self):
        vector = self.motion(self.run_snapshot(self.two_motions((1, 2), (1, 2))))["faults"][0]["relative_velocity_right_minus_left"]
        self.assertEqual(vector["speed"], 0)
        self.assertIsNone(vector["bearing_clockwise_from_north_deg"])

    def test_partial_components_propagate_independently_but_not_to_projections(self):
        fault = self.motion(self.run_snapshot(self.two_motions((None, 0), (3, 4))))["faults"][0]
        self.assertIsNone(fault["relative_velocity_right_minus_left"]["vx"])
        self.assertEqual(fault["relative_velocity_right_minus_left"]["vy"], 4)
        self.assertIsNone(fault["relative_velocity_right_minus_left"]["speed"])
        self.assertIsNone(fault["segments"][0]["tangential_velocity"])
        self.assertIsNone(fault["segments"][0]["right_normal_velocity"])

    def test_plate_crosswalk_does_not_imply_boundary_or_motion(self):
        decisions = self.decisions()
        decisions["blocks"] = [self.block("A-B01", None, None, "SYNTHETIC-P1"), self.block("A-B02", None, None, "SYNTHETIC-P2")]
        relation = self.run_snapshot(decisions)["products"][snapshot.PRODUCT_NAMES[1]]["features"][0]["properties"]["tectonic_relationship"]
        self.assertEqual(relation["left_plate_id"], "SYNTHETIC-P1")
        self.assertEqual(relation["right_plate_id"], "SYNTHETIC-P2")
        self.assertIsNone(relation["plate_boundary"])

    def test_explicit_boundary_false_is_preserved(self):
        decisions = self.decisions()
        decisions["faults"] = [{"fault_id": self.faults[0], "plate_boundary": False, "source_refs": ["synthetic"]}]
        relation = self.run_snapshot(decisions)["products"][snapshot.PRODUCT_NAMES[1]]["features"][0]["properties"]["tectonic_relationship"]
        self.assertIs(relation["plate_boundary"], False)
        self.assertEqual(relation["boundary_status"], "SUPPLIED_UNVERIFIED")

    def test_identical_plates_cannot_be_explicit_plate_boundary(self):
        decisions = self.decisions()
        decisions["blocks"] = [self.block("A-B01", None, None, "SYNTHETIC-P"), self.block("A-B02", None, None, "SYNTHETIC-P")]
        decisions["faults"] = [{"fault_id": self.faults[0], "plate_boundary": True, "source_refs": ["synthetic"]}]
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)

    def test_approved_strings_and_complete_synthetic_coverage_never_promote_authority(self):
        decisions = self.decisions()
        decisions["source_status"] = "APPROVED"
        decisions["source_refs"][0]["status"] = "CANON"
        decisions["blocks"] = [self.block(v, 0, 0, "SYNTHETIC-" + v) for v in self.blocks]
        decisions["faults"] = [{"fault_id": v, "plate_boundary": False, "source_refs": ["synthetic"]} for v in self.faults]
        result = self.run_snapshot(decisions)
        self.assertEqual(result["validation"]["status"], "COMPLETE_ENGINEERING_SNAPSHOT")
        for key in ("category_complete", "production_authorized", "source_claims_independently_verified"):
            self.assertIs(result["validation"][key], False)
        self.assertEqual(self.motion(result)["provenance"]["domain_decisions"]["source_status"], "APPROVED")

    def test_deterministic_read_only_and_no_caller_mutation(self):
        before = {v.name: v.read_bytes() for v in self.package.iterdir()}
        decisions = self.two_motions()
        original = copy.deepcopy(decisions)
        first, second = self.run_snapshot(decisions), self.run_snapshot(decisions)
        self.assertEqual(json.dumps(first, allow_nan=False), json.dumps(second, allow_nan=False))
        self.assertEqual(decisions, original)
        self.assertEqual(before, {v.name: v.read_bytes() for v in self.package.iterdir()})

    def test_preserves_segment_order_and_handles_duplicate_point(self):
        self.vector["features"][10]["geometry"]["coordinates"] = [[0, 0], [0, 0], [10, 0], [10, -10]]
        self.save_package()
        segments = self.motion(self.run_snapshot(self.two_motions()))["faults"][0]["segments"]
        self.assertEqual([v["segment_index"] for v in segments], [0, 1, 2])
        self.assertEqual(segments[0]["status"], "DEGENERATE_SEGMENT")
        self.assertIsNone(segments[0]["right_normal_velocity"])
        self.assertEqual(segments[1]["right_normal_velocity"], 4)
        self.assertEqual(segments[2]["right_normal_velocity"], 3)

    def test_all_degenerate_fault_fails(self):
        self.vector["features"][10]["geometry"]["coordinates"] = [[0, 0], [0, 0]]
        self.save_package()
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot()

    def test_mismatched_frames_units_or_schema_fail(self):
        for key, value in (("frame", "geographic_lon_lat"), ("velocity_units", "km/year"), ("schema_version", True), ("reference_frame", "")):
            with self.subTest(key=key):
                decisions = self.two_motions()
                decisions[key] = value
                with self.assertRaises(snapshot.SnapshotError):
                    self.run_snapshot(decisions)
        for key, value in (("frame", "x_north"), ("reference_frame", "other"), ("units", "m/year")):
            with self.subTest(motion_key=key):
                decisions = self.two_motions()
                decisions["blocks"][0]["velocity"][key] = value
                with self.assertRaises(snapshot.SnapshotError):
                    self.run_snapshot(decisions)

    def test_invalid_numeric_types_nonfinite_and_overflow_fail(self):
        for value in (True, "3", float("nan"), float("inf"), 10 ** 400):
            with self.subTest(value=str(value)[:20]):
                decisions = self.two_motions((value, 0))
                with self.assertRaises(snapshot.SnapshotError):
                    self.run_snapshot(decisions)
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(self.two_motions((-1e308, 0), (1e308, 0)))

    def test_unknown_extra_fields_and_unserialisable_values_fail(self):
        decisions = self.decisions()
        decisions["inferred_velocity_from_throw"] = 1
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)
        decisions = self.decisions()
        decisions["source_status"] = object()
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)

    def test_missing_locators_hashes_sources_and_relative_paths_fail(self):
        for key, value in (("locator", " "), ("sha256", "a" * 63), ("path", "relative.json"), ("status", "")):
            with self.subTest(key=key):
                decisions = self.decisions()
                decisions["source_refs"][0][key] = value
                with self.assertRaises(snapshot.SnapshotError):
                    self.run_snapshot(decisions)
        decisions = self.two_motions()
        decisions["blocks"][0]["velocity"]["source_refs"] = []
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)
        decisions = self.decisions()
        decisions["frame_source_refs"] = ["missing"]
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)

    def test_duplicate_and_unknown_decision_ids_fail(self):
        decisions = self.two_motions()
        decisions["blocks"].append(copy.deepcopy(decisions["blocks"][0]))
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)
        decisions = self.two_motions()
        decisions["blocks"][0]["block_id"] = "not-a-block"
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)
        decisions = self.decisions()
        decisions["source_refs"].append(copy.deepcopy(decisions["source_refs"][0]))
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)

    def test_integer_boundary_is_not_boolean(self):
        decisions = self.decisions()
        decisions["faults"] = [{"fault_id": self.faults[0], "plate_boundary": 1, "source_refs": ["synthetic"]}]
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot(decisions)

    def test_package_content_hash_and_exact_role_paths_fail_closed(self):
        name = snapshot.FILES["events"]
        (self.package / name).write_text("{}", encoding="utf-8")
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot()
        self.save_package()
        self.manifest["histories"]["A"]["artifacts"]["events"]["path"] = "other/" + name
        self.write(snapshot.MANIFEST, self.manifest)
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot()

    def test_wrong_history_and_missing_faults_fail(self):
        self.events["history"] = "B"
        self.save_package()
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot()
        self.events["history"] = "A"
        self.vector["features"].pop()
        self.save_package()
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot()

    def test_unresolved_source_sides_fail(self):
        self.vector["features"][10]["properties"]["right_block_id"] = "missing"
        self.save_package()
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot()

    def test_duplicate_json_key_and_nonfinite_input_fail(self):
        (self.package / snapshot.MANIFEST).write_text('{"status":"one","status":"two"}', encoding="utf-8")
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot()
        (self.package / snapshot.MANIFEST).write_text('{"status":NaN}', encoding="utf-8")
        with self.assertRaises(snapshot.SnapshotError):
            self.run_snapshot()

    def test_source_adjacency_and_motion_do_not_claim_spatial_validation(self):
        result = self.run_snapshot(self.two_motions())
        block = next(v for v in result["products"][snapshot.PRODUCT_NAMES[0]]["features"] if v["properties"]["block_id"] == "A-B01")
        adjacency = block["properties"]["tectonic_crosswalk"]["declared_fault_adjacency"]
        self.assertEqual([v["fault_id"] for v in adjacency], self.faults)
        self.assertEqual({v["neighbour_block_id"] for v in adjacency}, {"A-B02"})
        self.assertFalse(result["validation"]["geometry_audit_performed"])
        self.assertIsNone(self.motion(result)["faults"][0]["physical_slip_or_convergence_interpretation"])


if __name__ == "__main__":
    unittest.main()
