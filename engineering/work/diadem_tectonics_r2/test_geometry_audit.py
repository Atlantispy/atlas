"""Independent mutation tests on small retained vector documents, never a producer.

The fixture is R1's retained read-only replay. Tests copy its JSON into memory;
source bytes are rehashed afterwards. No arrays, images, or legacy code run.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import geometry_audit as g


PACKAGE = (Path(__file__).resolve().parents[2] / "outputs" / "diadem-tectonics-review-r1" /
           "verified-02" / "sandbox" / "work" / "stage4-rebuild")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GeometryMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if g.DEPENDENCY_ERROR:
            raise RuntimeError(g.DEPENDENCY_ERROR)
        cls.paths = [PACKAGE / (g.PREFIX + name + "." + extension)
                     for name, extension in (("events", "json"), ("faults-blocks", "geojson"),
                                             ("accommodation", "geojson"), ("provinces", "geojson"),
                                             ("sections", "geojson"))]
        cls.paths += [PACKAGE / "checkpoint0-frozen-inputs.json",
                      PACKAGE / "checkpoint1-event-model-audit-contract-review-only.json"]
        # Missing preserved fixtures are a test error, not an implicit PASS.
        cls.before = {path: digest(path) for path in cls.paths}
        cls.documents = {name: g._read(path) for name, path in zip(
            ("events", "faults-blocks", "accommodation", "provinces", "sections"), cls.paths)}
        cls.checkpoint = g._read(cls.paths[-2])
        cls.contract = g._read(cls.paths[-1])

    @classmethod
    def tearDownClass(cls):
        after = {path: digest(path) for path in cls.paths}
        if after != cls.before:
            raise AssertionError("retained fixture bytes changed during tests")

    def setUp(self):
        self.docs = copy.deepcopy(self.documents)
        self.cp = copy.deepcopy(self.checkpoint)
        self.rules = copy.deepcopy(self.contract)

    def context(self, arrays=None):
        return g.Context(self.docs, self.cp, self.rules, arrays)

    def feature(self, layer, identifier=None):
        for document in self.docs.values():
            for feature in document.get("features", []):
                p = feature["properties"]
                if p["layer"] == layer and (identifier is None or
                        p.get(g.ID_KEYS.get(layer, "section_id")) == identifier):
                    return feature
        raise AssertionError((layer, identifier))

    def fail_with(self, function, text):
        result = function(self.context())
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(any(text in item for item in result["metrics"]["issues"]), result)
        return result

    def test_baseline_measures_partition_and_does_not_reuse_historical_pass(self):
        result = g._partition(self.context())
        self.assertEqual(result["status"], "PASS", result)
        for key in ("gap_area_km2", "outside_area_km2", "overlap_area_km2"):
            self.assertEqual(result["metrics"][key], 0.0)
        self.assertIs(result["metrics"]["raster_part_checked_here"], False)
        graph = g._fault_graph(self.context())
        self.assertEqual(graph["status"], "FAIL")
        self.assertTrue(graph["metrics"]["unresolved_geometric_crossings"])
        self.assertTrue(graph["metrics"]["valid_degree_one_relay_terminals"])
        self.assertIs(graph["metrics"]["historical_auditor_reexecuted"], False)

    def test_unchanged_inventory_frame_crown_accommodation_provinces_sections(self):
        for check in (g._inventory, g._apron, g._crown,
                      g._accommodation, g._provinces, g._sections):
            with self.subTest(check=check.__name__):
                result = check(self.context())
                self.assertEqual(result["status"], "PASS", result)

    def test_named_block_kinematics_pass_but_boundary_derivation_is_unresolved(self):
        result = g._blocks(self.context())
        self.assertEqual(result["metrics"]["named_reference_and_kinematic_issues"], [])
        associations = result["metrics"]["regional_side_associations_not_declared_as_boundaries"]
        self.assertEqual(associations, sorted(associations))
        self.assertEqual(result["status"], "FAIL")
        self.assertGreater(result["metrics"]["internal_boundary_derivation"][
            "unique_unsupported_internal_boundary_length_km"], 0)
        self.assertIs(result["metrics"]["internal_boundary_derivation"]["domain_perimeter_excluded"], True)

    def test_missing_primary_layer_is_detected(self):
        self.docs["faults-blocks"]["features"] = [f for f in self.docs["faults-blocks"]["features"]
                                                if f["properties"]["layer"] != "crown_link"]
        self.fail_with(g._inventory, "missing primary layers")

    def test_duplicate_identifier_is_detected(self):
        self.docs["faults-blocks"]["features"].append(copy.deepcopy(self.feature("structural_block")))
        self.fail_with(g._inventory, "duplicate feature identifier")

    def test_invalid_polygon_is_detected(self):
        self.feature("structural_block")["geometry"]["coordinates"] = [[[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]]
        self.fail_with(g._inventory, "invalid geometry")

    def test_unclosed_polygon_is_not_silently_repaired_by_geometry_library(self):
        self.feature("structural_block")["geometry"]["coordinates"][0].pop()
        self.fail_with(g._inventory, "must be explicitly closed")

    def test_external_plan_coordinate_is_detected(self):
        self.feature("topology_node")["geometry"]["coordinates"] = [-1, 3]
        self.fail_with(g._apron, "outside public frame")

    def test_negative_section_depth_is_not_mistaken_for_external_apron(self):
        result = g._apron(self.context())
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(any(xy[1] < 0 for f in self.docs["sections"]["features"]
                            for xy in g._coordinates(f["geometry"]["coordinates"])))

    def test_translated_block_breaks_real_polygon_partition(self):
        coordinates = self.feature("structural_block", "A-B04")["geometry"]["coordinates"][0]
        for point in coordinates:
            point[0] += 0.5
        result = self.fail_with(g._partition, "block partition mismatch")
        self.assertGreater(result["metrics"]["gap_area_km2"], 0)
        self.assertGreater(result["metrics"]["overlap_area_km2"], 0)

    def test_domain_inventory_mutation_is_detected(self):
        self.feature("structural_model_domain")["properties"]["included_block_ids"].pop()
        self.fail_with(g._partition, "domain block inventory differs")

    def test_node_motion_adds_endpoint_failure_despite_existing_crossing_failure(self):
        self.feature("topology_node", "N001")["geometry"]["coordinates"][0] += 1
        self.fail_with(g._fault_graph, "endpoint does not match node N001")

    def test_node_incident_inventory_mutation_is_detected(self):
        self.feature("topology_node", "N001")["properties"]["incident_fault_ids"].pop()
        self.fail_with(g._fault_graph, "N001: node/fault incidence mismatch")

    def test_removing_relay_pair_breaks_valid_degree_one_exception(self):
        self.feature("fault_segment", "C-N-1")["properties"]["relay_pair_id_or_null"] = None
        self.fail_with(g._fault_graph, "CN02: unresolved degree-one relay_entry")

    def test_relay_metadata_does_not_excuse_actual_unexplained_crossing(self):
        result = g._fault_graph(self.context())
        pairs = {frozenset(item["faults"]) for item in result["metrics"]["unresolved_geometric_crossings"]}
        self.assertIn(frozenset(("C-N-1", "C-N-2")), pairs)
        self.assertEqual(self.feature("fault_segment", "C-N-1")["properties"]["relay_pair_id_or_null"],
                         self.feature("fault_segment", "C-N-2")["properties"]["relay_pair_id_or_null"])

    def test_unresolved_event_is_detected(self):
        self.feature("fault_segment", "A-WR-1")["properties"]["events_reactivated"] = ["E99"]
        self.fail_with(g._fault_graph, "invalid event references")

    def test_rank_polarity_inversion_is_detected(self):
        self.feature("structural_block", "A-B02")["properties"].update(
            relative_vertical_rank=5, relative_vertical_state="positive")
        self.fail_with(g._blocks, "downthrown rank not below upthrown rank")

    def test_false_declared_boundary_reference_is_detected(self):
        self.feature("structural_block", "A-B10")["properties"]["bounding_fault_ids"].append("A-WR-1")
        self.fail_with(g._blocks, "A-B10/A-WR-1: nonreciprocal block/fault reference")

    def test_missing_tilt_controller_is_detected(self):
        self.feature("structural_block", "A-B02")["properties"]["tilt_controlling_fault_id"] = None
        self.fail_with(g._blocks, "unresolved tilt controller")

    def test_massif_translation_breaks_containment_and_structural_support(self):
        for point in self.feature("massif_structural_envelope", "M-01")["geometry"]["coordinates"][0]:
            point[0] += 150
        self.fail_with(g._crown, "reference is outside its massif")

    def test_massif_source_provenance_removal_is_detected(self):
        self.feature("massif_structural_envelope", "M-01")["properties"]["source_feature_ids"].pop()
        self.fail_with(g._crown, "incomplete support provenance")

    def test_crown_member_mismatch_is_detected(self):
        self.feature("crown_system", "C-N")["properties"]["member_fault_ids"].pop()
        self.fail_with(g._crown, "uniquely cover all E1 segments")

    def test_extra_gate_closing_link_is_detected(self):
        link = copy.deepcopy(self.feature("crown_link"))
        link["properties"].update(link_id="CL-FALSE-GATE", from_haus="edelstein", to_haus="glanzgrund")
        self.docs["faults-blocks"]["features"].append(link)
        self.fail_with(g._crown, "sole Gate gap")

    def test_ellipse_diagnostic_detects_perfect_ellipse(self):
        t = g.np.arange(24) * 2 * g.np.pi / 24
        positions = g.np.column_stack((7 + 4*g.np.cos(t), 8 + 2*g.np.sin(t)))
        self.assertLess(g._ellipse_irregularity(positions)["q_std"], 1e-12)
        positions[3] += [1, 0]
        self.assertGreater(g._ellipse_irregularity(positions)["q_std"], 0.01)

    def test_disconnected_required_accommodation_edge_is_detected(self):
        self.docs["accommodation"]["features"] = [f for f in self.docs["accommodation"]["features"]
                                                  if f["properties"].get("connection_id") != "AC-L01"]
        result = self.fail_with(g._accommodation, "required accommodation connections missing")
        self.assertIn("accommodation graph is disconnected", result["metrics"]["issues"])

    def test_accommodation_endpoint_motion_is_detected(self):
        self.feature("accommodation_connection", "AC-L01")["geometry"]["coordinates"][0] = [10, 10]
        self.fail_with(g._accommodation, "connection geometry misses named compartments")

    def test_forbidden_island_array_is_detected(self):
        result = g._accommodation(self.context({"natural_island_high": None}))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("forbidden island array fields", result["metrics"]["issues"])

    def test_province_detachment_is_detected(self):
        for point in self.feature("geological_province", "P-GATE")["geometry"]["coordinates"][0]:
            point[1] += 700
        self.fail_with(g._provinces, "outside named parent blocks")

    def test_gate_activity_change_is_detected(self):
        self.feature("geological_province", "P-GATE")["properties"]["geothermal_state"] = "active_hot"
        self.fail_with(g._provinces, "Gate is not old, cool")

    def test_province_reciprocity_change_is_detected(self):
        self.feature("structural_block", "A-B10")["properties"]["province_ids"].remove("P-GATE")
        self.fail_with(g._provinces, "nonreciprocal province/block reference")

    def test_section_station_mutation_is_detected(self):
        self.feature("section_fault_plane")["properties"]["trace_station_km"] += 0.5
        self.fail_with(g._sections, "station/intersection geometry mismatch")

    def test_section_declared_fault_inventory_mutation_is_detected(self):
        self.feature("section_trace", "X1")["properties"]["intersected_fault_ids"].pop()
        self.fail_with(g._sections, "declared intersected faults differ")

    def test_section_dip_geometry_mutation_is_detected(self):
        coords = self.feature("section_fault_plane")["geometry"]["coordinates"]
        coords[-1][0] = coords[0][0] + 100
        self.fail_with(g._sections, "fault-plane dip/depth/polarity differs")

    def test_fracture_role_and_shorter_valid_depths_are_preserved(self):
        self.assertEqual(g._sections(self.context())["status"], "PASS")
        planes = self.docs["sections"]["features"]
        self.assertTrue(any(f["properties"]["layer"] == "section_fault_plane" and
                            f["geometry"]["coordinates"][-1][1] == -24 for f in planes))

    def test_section_boolean_scale_substitution_is_rejected(self):
        self.docs["sections"]["properties"]["identical_scales"] = 1
        self.fail_with(g._sections, "section display scales differ")

    def test_missing_package_and_invalid_json_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            results = g.audit_geometry(path, self.rules)
            self.assertEqual(len(results), 9)
            self.assertTrue(all(result["status"] == "FAIL" for result in results))
            for payload in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}'):
                file = path / "invalid.json"
                file.write_text(payload, encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    g._read(file)


class SyntheticBoundaryTests(unittest.TestCase):
    def context(self, fault_x=5):
        def feature(layer, properties, geometry):
            return {"type": "Feature", "properties": {"layer": layer, **properties}, "geometry": geometry}

        def polygon(x0, x1):
            return {"type": "Polygon", "coordinates": [[[x0, 0], [x1, 0], [x1, 10], [x0, 10], [x0, 0]]]}

        features = [feature("structural_model_domain", {"model_domain_id": "D"}, polygon(0, 10)),
                    feature("fault_segment", {"fault_id": "F"},
                            {"type": "LineString", "coordinates": [[fault_x, 0], [fault_x, 10]]})]
        for bid, x0, x1 in (("B1", 0, 5), ("B2", 5, 10)):
            features.append(feature("structural_block", {"block_id": bid,
                "bounding_fault_ids": ["F"], "non_fault_contact_ids": []}, polygon(x0, x1)))
        documents = {"events": {"events": [{"event_id": "E1"}]},
                     "faults-blocks": {"type": "FeatureCollection", "features": features}}
        for name in ("accommodation", "provinces", "sections"):
            documents[name] = {"type": "FeatureCollection", "features": []}
        return g.Context(documents, {}, {})

    def test_exact_internal_source_passes_without_faults_on_domain_perimeter(self):
        c = self.context()
        result = g._measure_block_edges(c, c.group("structural_block"))
        self.assertEqual(result["unique_unsupported_internal_boundary_length_km"], 0)
        self.assertAlmostEqual(result["per_block"]["B1"]["internal_boundary_length_km"], 10, places=6)
        self.assertIs(result["domain_perimeter_excluded"], True)

    def test_shifted_source_is_detected_and_shared_length_not_double_counted(self):
        c = self.context(5.1)
        result = g._measure_block_edges(c, c.group("structural_block"))
        self.assertAlmostEqual(result["unique_unsupported_internal_boundary_length_km"], 10, places=6)
        self.assertAlmostEqual(sum(r["unsupported_internal_length_km"] for r in result["per_block"].values()), 20, places=6)


if __name__ == "__main__":
    unittest.main()
