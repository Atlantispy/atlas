from __future__ import annotations

import unittest

import numpy as np

from hydrology_regeneration import (
    RegenerationError,
    anti_smoothing_gate,
    build_node_cost,
    densify_polyline,
    derive_regenerated_flow_evidence,
    validate_parent_conserving_elevation,
)
from synthetic_pilot import build_synthetic_evidence, run_synthetic_pilot


class RegenerationPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (
            cls.result,
            cls.arrays,
            cls.parent,
            cls.references,
            cls.store,
            cls.corridor,
            cls.old_axis,
            cls.topology,
            cls.config,
        ) = run_synthetic_pilot()
        derive_regenerated_flow_evidence(cls.arrays, cls.config.cell_size_m)

    def test_evidence_led_route_moves_and_improves(self):
        self.assertTrue(self.result.metrics["anti_smoothing_pass"])
        self.assertGreaterEqual(
            self.result.metrics["candidate_p95_displacement_m"], self.config.minimum_p95_displacement_m
        )
        self.assertGreaterEqual(
            self.result.metrics["evidence_cost_improvement_fraction"], self.config.minimum_cost_improvement
        )

    def test_topology_and_downhill_continuity_are_preserved(self):
        route = self.result.path_cells
        self.assertEqual(route[0], self.topology.source)
        self.assertEqual(route[-1], self.topology.receiver)
        self.assertIn(self.topology.ordered_contacts[0], route)
        elevations = np.asarray([self.arrays["elevation_m"][cell] for cell in route])
        self.assertLessEqual(float(np.diff(elevations).max(initial=0)), self.config.max_uphill_step_m + 1e-6)

    def test_width_and_discharge_vary_along_route(self):
        widths = np.asarray(self.result.width_m)
        discharge = np.asarray(self.result.discharge_m3_s)
        self.assertGreater(float(np.ptp(widths)), 0.10)
        self.assertGreater(float(np.ptp(discharge)), 0.01)
        self.assertIn("width_equation", self.result.lineage["hydraulic_geometry_assumptions"])

    def test_full_ref_patch_tile_semantics_are_used(self):
        kinds = self.result.lineage["cache_reference_kinds"]
        self.assertIn("full", kinds.values())
        self.assertIn("ref", kinds.values())
        self.assertIn("patch", kinds.values())
        resolved = self.store.resolve(self.references["runoff_mm_y"])
        np.testing.assert_array_equal(resolved, self.arrays["runoff_mm_y"])

    def test_route_is_sensitive_to_changed_terrain_forcing(self):
        opposite, *_ = run_synthetic_pilot(valley_amplitude=-6.0)
        first = set(self.result.path_cells)
        second = set(opposite.path_cells)
        overlap = len(first & second) / max(len(first | second), 1)
        self.assertLess(overlap, 0.55)
        self.assertNotEqual(self.result.lineage["route_cell_hash"], opposite.lineage["route_cell_hash"])

    def test_evidence_supported_coincidence_is_not_forced_to_move(self):
        straight_valley, *_ = run_synthetic_pilot(valley_amplitude=0.0)
        self.assertEqual(straight_valley.metrics["anti_smoothing_reason"], "PASS_COINCIDENT_EVIDENCE_OPTIMUM")
        self.assertTrue(straight_valley.metrics["routed_by_evidence_engine"])
        self.assertFalse(straight_valley.metrics["inherited_axis_used_in_objective"])

    def test_exact_inherited_axis_is_rejected(self):
        old = densify_polyline(self.old_axis)
        node_cost = build_node_cost(self.arrays, self.corridor)
        with self.assertRaisesRegex(RegenerationError, "REJECT_INHERITED_AXIS_REPRODUCTION"):
            anti_smoothing_gate(old, self.old_axis, self.arrays, node_cost, self.config)

    def test_cosmetic_one_cell_smoothing_is_rejected(self):
        old = densify_polyline(self.old_axis)
        cosmetic = [old[0], *[(row + 1, col) for row, col in old[1:-1]], old[-1]]
        node_cost = build_node_cost(self.arrays, self.corridor)
        with self.assertRaisesRegex(RegenerationError, "REJECT_COSMETIC_SMOOTHING"):
            anti_smoothing_gate(cosmetic, self.old_axis, self.arrays, node_cost, self.config)

    def test_repeated_parent_pixels_are_rejected(self):
        repeated = np.repeat(np.repeat(self.parent, 10, axis=0), 10, axis=1)
        with self.assertRaisesRegex(RegenerationError, "repeat parent pixels"):
            validate_parent_conserving_elevation(repeated, self.parent)

    def test_parent_resolution_and_uncertainty_are_explicit(self):
        self.assertEqual(self.result.lineage["cell_size_m"], 10.0)
        self.assertEqual(self.result.lineage["model_resolution_m"], 10.0)
        self.assertEqual(self.result.lineage["physical_source_resolution_m"], 100.0)
        self.assertEqual(self.result.lineage["effective_evidence_resolution_m"], 100.0)
        self.assertEqual(self.result.lineage["uncertainty_class"], "MODELLED_10M_REVIEW_ONLY")
        self.assertTrue(self.result.lineage["not_a_surveyed_10m_dem"])
        self.assertIn("Y/row increases south", self.result.lineage["axis_convention"])

    def test_route_conditioned_discharge_never_resets_downstream(self):
        discharge = np.asarray(self.result.discharge_m3_s)
        self.assertGreaterEqual(float(np.diff(discharge).min(initial=0.0)), -1e-8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
