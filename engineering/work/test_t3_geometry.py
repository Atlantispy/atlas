"""Focused equivalence and boundary tests for the bounded tectonics successor."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from work.diadem_tectonics_r2 import geometry_audit as old
from work.diadem_tectonics_r3 import geometry_audit as new
from work.diadem_tectonics_r3 import audit

PACKAGE = (Path(__file__).resolve().parents[1] / "outputs/diadem-tectonics-review-r1/"
           "verified-02/sandbox/work/stage4-rebuild")


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = [PACKAGE / f"{new.PREFIX}{name}.{ext}" for name, ext in new.DOCUMENT_FILES]
        cls.paths += [PACKAGE / "checkpoint0-frozen-inputs.json",
                      PACKAGE / "checkpoint1-event-model-audit-contract-review-only.json"]
        cls.before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.paths}
        cls.documents = {name: old._read(path) for (name, _), path in zip(new.DOCUMENT_FILES, cls.paths)}
        cls.checkpoint = old._read(cls.paths[-2])
        cls.contract = old._read(cls.paths[-1])

    @classmethod
    def tearDownClass(cls):
        if {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.paths} != cls.before:
            raise AssertionError("Retained geometry fixture changed")

    def context(self, module, documents=None):
        return module.Context(deepcopy(self.documents if documents is None else documents),
                              deepcopy(self.checkpoint), deepcopy(self.contract))

    def test_full_geometry_output_including_existing_failures_is_exact(self):
        expected = old.audit_geometry(PACKAGE, self.contract)
        self.assertEqual(new.audit_geometry(PACKAGE, self.contract), expected)
        self.assertEqual([r["code"] for r in expected if r["status"] == "FAIL"],
                         ["FAULT_GRAPH_SCHEMA_AND_TOPOLOGY", "BLOCK_KINEMATIC_DERIVATION"])
        crossings = expected[3]["metrics"]["unresolved_geometric_crossings"]
        self.assertEqual(len(crossings), 6)

    def test_bounds_keep_distance_roundoff_boundary_and_intersection_multiplicity(self):
        line = new.LineString([(0, 0), (1, 0)])
        for distance in (0., math.nextafter(new.EPS_KM, 0.), new.EPS_KM,
                         math.nextafter(new.EPS_KM, math.inf), 2*new.EPS_KM):
            point = new.Point(.5, distance)
            if point.distance(line) <= new.EPS_KM:
                self.assertTrue(new._bounds_may_meet(line.bounds, point.bounds))
        cases = [new.LineString([(0, 0), (1, 0)]),
                 new.LineString([(.5, -1), (.5, 1)]),
                 new.LineString([(0, 1), (.25, -1), (.75, 1), (1, -1)]),
                 new.LineString([(20, 1), (21, 2)])]
        for other in cases:
            intersection = line.intersection(other)
            if not intersection.is_empty:
                self.assertTrue(new._bounds_may_meet(line.bounds, other.bounds))
                self.assertEqual(line.intersection(other).wkb, intersection.wkb)
        self.assertFalse(new._bounds_may_meet(line.bounds, cases[-1].bounds))

    def test_real_graph_overlap_and_node_boundary_failures_remain_exact(self):
        for alteration in ("overlap", "near", "outside"):
            documents = deepcopy(self.documents)
            features = documents["faults-blocks"]["features"]
            faults = [f for f in features if f["properties"]["layer"] == "fault_segment"]
            if alteration == "overlap":
                faults[1]["geometry"] = deepcopy(faults[0]["geometry"])
            else:
                nid = faults[0]["properties"]["start_node_id"]
                node = next(f for f in features if f["properties"].get("node_id") == nid)
                node["geometry"]["coordinates"][0] += new.EPS_KM * (0.5 if alteration == "near" else 2)
            with self.subTest(alteration=alteration):
                self.assertEqual(new._fault_graph(self.context(new, documents)),
                                 old._fault_graph(self.context(old, documents)))

    def test_section_plane_multiplicity_order_and_malformed_ids_remain_exact(self):
        documents = deepcopy(self.documents)
        plane = next(f for f in documents["sections"]["features"]
                     if f["properties"]["layer"] == "section_fault_plane")
        documents["sections"]["features"].append(deepcopy(plane))
        self.assertEqual(new._sections(self.context(new, documents)),
                         old._sections(self.context(old, documents)))
        bad = deepcopy(plane)
        bad["properties"]["section_id"] = ["X1"]
        documents["sections"]["features"].append(bad)
        for module in (old, new):
            with self.subTest(module=module.__name__), self.assertRaisesRegex(TypeError, "unhashable type: 'list'"):
                module._sections(self.context(module, documents))

    def test_invocation_lookup_caches_are_local_and_keep_original_order(self):
        context = self.context(new)
        reference = self.context(old)
        for layer in ("fault_segment", "structural_block", "massif_structural_envelope"):
            self.assertEqual(context.group(layer), reference.group(layer))
            self.assertIs(context.group(layer), context.group(layer))
        feature = next(iter(context.group("massif_structural_envelope").values()))
        self.assertEqual(context.centroid(feature).wkb, context.geom(feature).centroid.wkb)
        self.assertIs(context.centroid(feature), context.centroid(feature))
        for sid in self.contract["required_section_ids"]:
            self.assertEqual(context.section_entries(sid),
                             [f for f in context.sections if f["properties"].get("section_id") == sid])
        self.assertIsNot(context.group("fault_segment"), self.context(new).group("fault_segment"))

    def test_fresh_decoded_bridge_never_rereads_or_reuses_a_previous_invocation(self):
        inputs = new._DecodedInputs(PACKAGE)
        for path in self.paths[:-1]:
            audit._json(path, _geometry_inputs=inputs)
        with patch.object(new, "_read", side_effect=AssertionError("duplicate geometry read")):
            result = new._audit_geometry(PACKAGE, self.contract, _inputs=inputs)
        self.assertEqual(result, old.audit_geometry(PACKAGE, self.contract))
        repeated = new._audit_geometry(PACKAGE, self.contract, _inputs=inputs)
        self.assertTrue(all(row["status"] == "FAIL" for row in repeated))
        self.assertIn("one exact audit invocation", repeated[0]["metrics"]["issues"][0])


class StrictReaderTests(unittest.TestCase):
    def test_retained_decoders_use_private_captured_source_identities(self):
        for name, module in (("sources", audit.sources), ("compare", audit.array_reader)):
            self.assertEqual(module.__name__, "_history_a_r3_r1_" + name)
            self.assertEqual(module._R12_EXECUTED_SHA256,
                             hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())

    def test_combined_reader_rejects_duplicate_nonfinite_nonobject_and_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / (new.PREFIX + "events.json")
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]'):
                path.write_bytes(raw)
                with self.subTest(raw=raw), self.assertRaises(audit.sources.SourceGateError):
                    audit._json(path, _geometry_inputs=new._DecodedInputs(root))
            path.write_bytes(b'{"x":1234567890}')
            with patch.object(audit.sources, "MAX_JSON_BYTES", 5), self.assertRaisesRegex(ValueError, "Oversized"):
                audit._json(path, _geometry_inputs=new._DecodedInputs(root))

    def test_geometry_bom_and_smaller_geometry_bound_errors_match_standalone(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / (new.PREFIX + "events.json")
            for raw, size_limit in ((b'\xef\xbb\xbf{"events":[]}', new.MAX_JSON_BYTES),
                                    (b'{"events":[]}', 4)):
                path.write_bytes(raw)
                with patch.object(new, "MAX_JSON_BYTES", size_limit):
                    try:
                        new._read(path)
                    except Exception as exc:
                        expected = f"{type(exc).__name__}: {exc}"
                    else:
                        self.fail("Expected strict geometry rejection")
                    inputs = new._DecodedInputs(root)
                    audit._json(path, _geometry_inputs=inputs)
                    result = new._audit_geometry(root, {}, _inputs=inputs)
                    self.assertTrue(all(row["status"] == "FAIL" for row in result))
                    self.assertEqual(result[0]["metrics"]["issues"], [expected])

    def test_decoded_bridge_rejects_wrong_package_and_duplicate_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / (new.PREFIX + "events.json")
            path.write_bytes(b'{"events":[]}')
            inputs = new._DecodedInputs(root)
            audit._json(path, _geometry_inputs=inputs)
            with self.assertRaisesRegex(ValueError, "uniqueness"):
                audit._json(path, _geometry_inputs=inputs)
            with self.assertRaisesRegex(ValueError, "one exact audit invocation"):
                inputs._take(root / "another")


if __name__ == "__main__":
    unittest.main()
