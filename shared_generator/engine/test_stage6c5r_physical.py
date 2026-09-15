"""Focused safety tests for the Stage 6C.5R physical 10 m kernel.

These fixtures are deliberately synthetic.  They test the invariants needed
before a real-site pilot without pretending that synthetic terrain validates
the Diadem's geography.
"""

from __future__ import annotations

import unittest

import numpy as np

from stage6c5r_physical import (
    CELL_SIZE_M,
    CLASS_CODE,
    ChannelConstraint,
    PhysicalRecipe,
    PhysicalReconstructionError,
    accumulate_flow,
    build_physical_context,
    condition_terrain,
    d8_receivers,
    mfd_receivers,
    parent_block_means,
    prepare_channel_beds,
    priority_flood_surface,
)


def _base_surface(rows: int = 30, cols: int = 30) -> np.ndarray:
    """Return a detailed but exactly parent-conserving descending surface."""

    row, col = np.indices((rows, cols), dtype=np.float64)
    parent = 160.0 - 0.35 * (row // 10) - 0.20 * (col // 10)
    # Every 10 x 10 block gets the same centred fine pattern, whose mean is 0.
    local_row = (row % 10) - 4.5
    local_col = (col % 10) - 4.5
    fine = -0.010 * local_row - 0.006 * local_col
    return (parent + fine).astype(np.float32)


def _monthly_runoff(rows: int = 30, cols: int = 30) -> np.ndarray:
    month = np.arange(12, dtype=np.float32)[:, None, None]
    return np.broadcast_to(30.0 + month, (12, rows, cols)).copy()


def _receiver_from_direction(direction: np.ndarray) -> np.ndarray:
    offsets = (
        (-1, 0),
        (-1, 1),
        (0, 1),
        (1, 1),
        (1, 0),
        (1, -1),
        (0, -1),
        (-1, -1),
    )
    rows, cols = direction.shape
    receiver = np.full(rows * cols, -1, dtype=np.int64)
    for row, col in np.ndindex(direction.shape):
        code = int(direction[row, col])
        if code >= 0:
            dr, dc = offsets[code]
            receiver[row * cols + col] = (row + dr) * cols + col + dc
    return receiver


class Stage6C5RPhysicalKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = _base_surface()
        self.parent = parent_block_means(self.base)
        self.constraint = ChannelConstraint(
            feature_id="SYNTHETIC-PROTECTED-R1",
            route_class="tier1",
            persistence="intermittent",
            path_cells=tuple((row, 15) for row in range(2, 28)),
            contributing_area_prior_km2=2.5,
            boundary_inflow=True,
            source_kind="synthetic_test_fixture",
        )

    def test_conditioning_conserves_each_parent_and_respects_one_metre_budget(self) -> None:
        conditioned, delta, protected, metrics = condition_terrain(
            self.base,
            self.parent,
            [self.constraint],
            PhysicalRecipe(),
        )
        error = np.abs(parent_block_means(conditioned) - self.parent)
        self.assertLessEqual(float(error.max()), 0.0051)
        self.assertLessEqual(float(np.abs(delta).max()), 1.0)
        self.assertLessEqual(metrics["maximum_parent_mean_error_m"], 0.0051)
        self.assertLessEqual(metrics["conditioning_delta_max_abs_m"], 1.0)
        self.assertTrue(np.any(protected == CLASS_CODE["tier1"]))
        path = list(self.constraint.path_cells)
        if conditioned[path[0]] < conditioned[path[-1]]:
            path.reverse()
        self.assertTrue(all(conditioned[source] > conditioned[target] for source, target in zip(path[:-1], path[1:])))
        self.assertTrue(metrics["channel_bed_is_separate_from_land_surface"])
        self.assertIsNone(metrics["minimum_final_protected_drop_m"])

    def test_mfd_dominant_code_matches_published_weights(self) -> None:
        row, col = np.indices(self.base.shape, dtype=np.float64)
        routing = 200.0 - 0.013 * row - 0.011 * col + 1e-7 * np.sin(row + col)
        weights_receiver, weights, direction = mfd_receivers(
            routing,
            np.zeros(self.base.shape, dtype=bool),
        )
        del weights_receiver
        stored = weights.reshape(8, *self.base.shape)
        active = stored.sum(axis=0) > 0.0
        selected = np.take_along_axis(stored, direction.clip(min=0)[None, :, :], axis=0)[0]
        self.assertTrue(np.all((direction[active] >= 0) & (direction[active] < 8)))
        self.assertTrue(np.all(selected[active] == np.max(stored, axis=0)[active]))

    def test_d8_receivers_are_strictly_downhill_and_acyclic(self) -> None:
        sink = np.zeros(self.base.shape, dtype=bool)
        routed, _, _ = priority_flood_surface(self.base, sink, 0.001)
        receiver, direction = d8_receivers(routed, sink)
        flat = routed.ravel().astype(np.float64)
        sources = np.flatnonzero(receiver >= 0)
        self.assertGreater(sources.size, 0)
        self.assertTrue(np.all(flat[sources] > flat[receiver[sources]]))

        # A complete topological accumulation is the independent cycle check.
        _, _, _, metrics = accumulate_flow(
            routed,
            receiver,
            _monthly_runoff(),
            {},
        )
        self.assertEqual(metrics["receiver_cycle_count"], 0)
        self.assertEqual(metrics["topologically_processed_cell_count"], self.base.size)
        self.assertEqual(direction.shape, self.base.shape)

    def test_accumulator_rejects_a_cycle(self) -> None:
        routing = np.asarray([[2.0, 1.0]], dtype=np.float32)
        receiver = np.asarray([1, 0], dtype=np.int64)
        runoff = np.ones((12, 1, 2), dtype=np.float32)
        with self.assertRaisesRegex(PhysicalReconstructionError, "cycle"):
            accumulate_flow(routing, receiver, runoff, {})

    def test_profile_above_terrain_fails_without_explicit_reconciliation(self) -> None:
        conflict = ChannelConstraint(
            feature_id="SYNTHETIC-CONFLICT",
            route_class="major",
            persistence="perennial",
            path_cells=((2, 2), (3, 2), (4, 2)),
            bed_elevations_m=(500.0, 499.0, 498.0),
        )
        with self.assertRaisesRegex(
            PhysicalReconstructionError, "CONFLICT_PROFILE_ABOVE_TERRAIN"
        ):
            prepare_channel_beds(self.base, [conflict], PhysicalRecipe())

    def test_explicit_review_candidate_is_reconciled_below_terrain(self) -> None:
        source_values = (500.0, 499.0, 498.0)
        candidate = ChannelConstraint(
            feature_id="SYNTHETIC-RECONCILED-CANDIDATE",
            route_class="major",
            persistence="perennial",
            path_cells=((2, 2), (3, 2), (4, 2)),
            bed_elevations_m=source_values,
            terrain_ceiling_reconciliation_allowed=True,
        )
        prepared, bed_grid, metrics = prepare_channel_beds(
            self.base, [candidate], PhysicalRecipe()
        )
        self.assertEqual(candidate.bed_elevations_m, source_values)
        self.assertEqual(metrics["protected_bed_above_conditioned_land_cell_count"], 0)
        self.assertGreater(metrics["protected_bed_terrain_ceiling_correction_max_m"], 0.0)
        self.assertGreater(metrics["protected_bed_terrain_ceiling_correction_cell_count"], 0)
        for cell, value in zip(prepared[0].path_cells, prepared[0].bed_elevations_m):
            self.assertLess(value, float(self.base[cell]))
            self.assertEqual(value, float(bed_grid[cell]))

    def test_priority_flood_preserves_high_elevation_sub_float32_epsilon(self) -> None:
        elevation = np.full((3, 3), 5000.0, dtype=np.float64)
        sink = np.zeros((3, 3), dtype=bool)
        routed, delta, _ = priority_flood_surface(elevation, sink, 0.0001)
        self.assertEqual(routed.dtype, np.dtype("f8"))
        self.assertEqual(delta.dtype, np.dtype("f8"))
        self.assertGreater(float(routed[1, 1]), 5000.0)

    def test_boundary_inflow_is_injected_and_propagated(self) -> None:
        rows, cols = 3, 3
        routing = np.asarray(
            [[9.0, 8.0, 7.0], [6.0, 5.0, 4.0], [3.0, 2.0, 1.0]],
            dtype=np.float32,
        )
        sink = np.zeros((rows, cols), dtype=bool)
        receiver, _ = d8_receivers(routing, sink)
        runoff = np.ones((12, rows, cols), dtype=np.float32)
        seed_index = 4
        seed_area = 7.25
        area, _, _, metrics = accumulate_flow(
            routing,
            receiver,
            runoff,
            {seed_index: seed_area},
        )
        self.assertEqual(metrics["boundary_seed_count"], 1)
        self.assertAlmostEqual(metrics["boundary_seed_area_km2"], seed_area)
        self.assertGreaterEqual(float(area.ravel()[seed_index]), seed_area + 0.0001 - 1e-6)
        downstream = int(receiver[seed_index])
        if downstream >= 0:
            self.assertGreaterEqual(float(area.ravel()[downstream]), seed_area + 0.0002 - 1e-6)

    def test_boundary_channel_inflow_enters_the_bounded_window(self) -> None:
        constraint = ChannelConstraint(
            feature_id="SYNTHETIC-BOUNDARY-INFLOW",
            route_class="tier1",
            persistence="intermittent",
            path_cells=tuple((row, 15) for row in range(0, 21)),
            contributing_area_prior_km2=3.0,
            boundary_inflow=True,
            source_kind="synthetic_test_fixture",
        )
        context = build_physical_context(
            self.base,
            self.parent,
            _monthly_runoff(),
            [constraint],
            np.ones(self.base.shape, dtype=bool),
            np.zeros(self.base.shape, dtype=bool),
            np.zeros(self.base.shape, dtype=np.uint8),
            np.zeros(self.base.shape, dtype=np.float32),
        )
        area = context.arrays["accumulated_area_km2"]
        self.assertGreaterEqual(float(area[1, 15]), 3.0)

    def test_generated_drainage_never_promotes_protected_channel_authority(self) -> None:
        recipe = PhysicalRecipe(
            generated_threshold_wet_km2=0.0002,
            generated_threshold_dry_km2=0.0002,
        )
        context = build_physical_context(
            self.base,
            self.parent,
            _monthly_runoff(),
            [],
            np.ones(self.base.shape, dtype=bool),
            np.zeros(self.base.shape, dtype=bool),
            np.zeros(self.base.shape, dtype=np.uint8),
            np.zeros(self.base.shape, dtype=np.float32),
            recipe=recipe,
            source_lineage={"fixture": "synthetic_only"},
        )
        protected = context.arrays["protected_channel_class"]
        potential = context.arrays["drainage_potential_or_protected_class"]
        self.assertTrue(np.all(protected == CLASS_CODE["none"]))
        self.assertTrue(np.any((potential >= CLASS_CODE["generated_ephemeral"]) & (potential <= CLASS_CODE["generated_perennial"])))
        self.assertTrue(np.all(context.arrays["channel_width_proxy_m"] == 0.0))
        self.assertTrue(np.all(context.arrays["flood_potential"] == 0.0))
        self.assertIn("NOT_ADDED_TO_CURRENT_NETWORK", context.lineage["generated_drainage_status"])
        self.assertIn("REGISTERED_PROTECTED_NETWORK", context.lineage["flood_wetness_channel_basis"])

    def test_build_is_deterministic_and_lineage_is_explicitly_review_only(self) -> None:
        kwargs = dict(
            base_elevation_m=self.base,
            parent_elevation_m=self.parent,
            monthly_runoff_mm=_monthly_runoff(),
            constraints=[self.constraint],
            land_mask=np.ones(self.base.shape, dtype=bool),
            sea_or_lake_sink_mask=np.zeros(self.base.shape, dtype=bool),
            inherited_flood=np.zeros(self.base.shape, dtype=np.uint8),
            inherited_wetland=np.zeros(self.base.shape, dtype=np.float32),
            source_lineage={"fixture": "synthetic_only"},
        )
        first = build_physical_context(**kwargs)
        second = build_physical_context(**kwargs)
        self.assertEqual(first.metrics["boundary_seed_count"], 1)
        self.assertAlmostEqual(first.metrics["boundary_seed_area_km2"], 2.5)
        self.assertEqual(first.metrics["array_digest"], second.metrics["array_digest"])
        self.assertEqual(first.lineage, second.lineage)
        for name in first.arrays:
            np.testing.assert_array_equal(first.arrays[name], second.arrays[name])

        lineage_text = str(first.lineage).upper()
        self.assertIn("REVIEW_ONLY", lineage_text)
        self.assertIn("NOT_CANON", lineage_text)
        self.assertTrue(first.lineage["not_a_surveyed_10m_dem"])
        self.assertIn("NOT_OBSERVED_RUNOFF", first.lineage["runoff_status"])
        self.assertIn("NOT_OBSERVED_WIDTH", first.lineage["width_status"])
        self.assertEqual(first.lineage["terrain_physical_source_resolution_m"], 100)
        self.assertEqual(first.lineage["model_resolution_m"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
