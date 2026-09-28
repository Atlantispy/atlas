"""Real bounded producer controls plus case and physical-claim refusal checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"tools"), str(ROOT/"src")]
import check_i01_junction_feasibility as control


class JunctionFeasibilityTests(unittest.TestCase):
    def test_real_multidirectional_mechanics_and_unissued_topology(self):
        result = control.controls(json.loads(control.CASE.read_text(encoding="utf-8")))
        self.assertTrue(result["passed"], result["checks"])
        self.assertFalse(result["generated_reorganisation"])
        self.assertFalse(result["physical_topology_issued"])
        self.assertGreater(len(result["missing_physical_conditions"]), 0)
        self.assertEqual(set(result["measurements"]["residuals"]),
            {"x", "y", "both", "reordered", "frame_rotated", "material_x", "material_y", "material_y_same_force"})

    def test_predeclared_case_cannot_weaken_acceptance_or_enable_birth(self):
        for key, value in (("absolute_tolerance", 1.), ("generated_reorganisation_enabled", True),
                           ("cells", [3, 3, 3]), ("corridor_width_m", .1), ("maximum_seconds", 600.)):
            changed = deepcopy(control.EXPECTED)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                control.validate_case(changed)

    def test_failures_and_changed_sources_cannot_report_pass(self):
        with patch.object(control, "controls", side_effect=RuntimeError("declared failure")):
            result = control.report()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["error"], "declared failure")
        with patch.object(control, "bindings", side_effect=[{"source": "old"}, {"source": "new"}]), \
             patch.object(control, "controls", return_value={"passed": True}):
            result = control.report()
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["source_unchanged"])
        self.assertFalse(result["scientific_acceptance"])


if __name__ == "__main__":
    unittest.main()
