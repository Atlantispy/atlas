from __future__ import annotations

import json
from pathlib import Path
import unittest

from diadem_contract.acceptance import compare_artifact, rule_for_family
from diadem_contract.validation import validate_document


ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((ROOT / "contract/preservation_matrix.v1.json").read_text(encoding="utf-8"))


class AcceptanceComparatorTests(unittest.TestCase):
    def test_preservation_matrix_is_valid_and_active(self):
        result = validate_document(MATRIX)
        self.assertTrue(result.passed, result.as_dict())
        self.assertEqual(MATRIX["status"], "ACTIVE_ENGINEERING_CONTRACT")

    def test_exact_canonical_ignores_object_key_order_only(self):
        rule = rule_for_family(MATRIX, "categorical_results")
        self.assertTrue(compare_artifact({"a": 1, "b": 2}, {"b": 2, "a": 1}, rule).passed)
        self.assertFalse(compare_artifact({"a": 1}, {"a": 2}, rule).passed)

    def test_topology_ignores_node_edge_listing_order_but_not_connections(self):
        rule = rule_for_family(MATRIX, "topology_graph")
        first = {"nodes": [{"id": "A"}, {"id": "B"}], "edges": [{"source": "A", "target": "B"}]}
        reordered = {"edges": [{"target": "B", "source": "A"}], "nodes": [{"id": "B"}, {"id": "A"}]}
        changed = {"nodes": [{"id": "A"}, {"id": "B"}], "edges": [{"source": "B", "target": "A"}]}
        self.assertTrue(compare_artifact(first, reordered, rule).passed)
        self.assertFalse(compare_artifact(first, changed, rule).passed)

    def test_pinned_float_bits_are_exact(self):
        rule = rule_for_family(MATRIX, "floating_array_pinned")
        self.assertTrue(compare_artifact(b"\x00\x01", b"\x00\x01", rule).passed)
        self.assertFalse(compare_artifact(b"\x00\x01", b"\x00\x02", rule).passed)

    def test_portable_float_tolerance_has_pass_and_fail_boundaries(self):
        rule = rule_for_family(MATRIX, "float32_elevation_portable")
        context = {name: rule[name] for name in ("producer_id", "layer_id", "unit")}
        passed = compare_artifact([1.0, 2.0], [1.0000005, 1.9999995], rule, context=context)
        failed = compare_artifact([1.0, 2.0], [1.01, 2.0], rule, context=context)
        self.assertTrue(passed.passed, passed.as_dict())
        self.assertFalse(failed.passed)
        self.assertEqual(failed.mismatch_count, 1)

    def test_portable_tolerance_fails_closed_without_exact_scope(self):
        rule = rule_for_family(MATRIX, "float32_elevation_portable")
        missing = compare_artifact([1.0], [1.0], rule)
        wrong = compare_artifact(
            [1.0],
            [1.0],
            rule,
            context={"producer_id": rule["producer_id"], "layer_id": rule["layer_id"], "unit": "km"},
        )
        self.assertFalse(missing.passed)
        self.assertFalse(wrong.passed)

    def test_internal_scheduler_history_is_not_a_published_parity_target(self):
        rule = rule_for_family(MATRIX, "internal_scheduler_history")
        self.assertTrue(compare_artifact({"worker": 1}, {"worker": 99}, rule).passed)


if __name__ == "__main__":
    unittest.main()
