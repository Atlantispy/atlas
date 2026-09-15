"""Synthetic lifecycle tests; no geographical sources are opened or generated."""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

import build_stage6c_100m as s6c
import build_stage6d_population as s6d
import generation_runtime as runtime

FIXTURE_ROOT = Path(__file__).resolve().parents[2]


class FixtureDirectory(tempfile.TemporaryDirectory):
    def cleanup(self):
        # The installed Windows runtime may create >260-character checkpoint
        # names correctly while shutil's ordinary-path cleanup cannot see them.
        if os.name == "nt" and not self.name.startswith("\\\\?\\"):
            self.name = "\\\\?\\" + str(Path(self.name).resolve())
        super().cleanup()


class AssessmentCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = FixtureDirectory(dir=FIXTURE_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sites = [s6c.Site(
            settlement_id=f"S{index}", x=x, y=10.0, barony_id=1,
            active_location=0, active_settlement=0, added_identity=0,
            conditionality=None, functional_tier=None, realised_form=None,
            form_family=None, vertical_domain="SURFACE", ordinary_human=0,
        ) for index, x in enumerate((10.0, 130.0))]
        self.coordinates = [{
            "settlement_id": site.settlement_id,
            "original_display_x_km": site.x, "original_display_y_km": site.y,
            "coordinate_semantics_code": "SYNTHETIC", "coordinate_value_resolution_km": 1.0,
            "coordinate_precision_basis": "TEST", "anchor_status": "TEST",
            "provisional_anchor": 0, "horizontal_uncertainty_shape": "TEST",
            "horizontal_uncertainty_radius_km": 1.0,
            "vertical_uncertainty_status": "TEST", "footprint_status": "TEST",
        } for site in self.sites]
        self.distance_calls = []
        self.fail_second = False
        owner = self

        class Raster:
            def __init__(self, _authority):
                pass

            def read_block(self, row, col, height, width):
                return {name: np.zeros((height, width), dtype=np.float32)
                        for name in ("sea", "wetland", "seren", "slope", "terrain", "flood_exposure")}

            def close(self):
                pass

        class Vectors:
            hydrology_composition = {"synthetic": 1}

            def __init__(self, _mode):
                pass

            def candidate_distance_batch(self, xs, ys, sites):
                owner.distance_calls.extend(site.settlement_id for site in sites)
                if owner.fail_second and sites[0].settlement_id == "S1":
                    raise RuntimeError("injected second-group interruption")
                count = len(sites)
                return SimpleNamespace(
                    active_cells=np.zeros((count, 100)),
                    perennial_cells=np.zeros((count, 100)), lagoon_cells={},
                    class_minima={name: np.zeros(count) for name in
                                  ("major", "minor", "special", "lake", "seasonal_lake", "coast")},
                )

        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.raster_constructor = stack.enter_context(mock.patch.object(s6c, "RasterStack", Raster))
        stack.enter_context(mock.patch.object(s6c, "VectorStack", Vectors))
        stack.enter_context(mock.patch.object(s6c, "ExactSurfaceIndex", side_effect=lambda *_: SimpleNamespace(
            rasterize_window=lambda row, col, height, width: np.ones((height, width), dtype=np.int32))))
        stack.enter_context(mock.patch.object(s6c, "source_fingerprint_identity", return_value={"fixture": "v1"}))
        stack.enter_context(mock.patch.object(s6c, "domain_candidate_mask", return_value=(
            np.ones(100, dtype=bool), np.ones(100), False)))
        self.store = runtime.CheckpointStore(self.root / "groups", "fixture-implementation-v1")

    def run_assessment(self, store=None, sites=None, stats=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return s6c.assess_all_sites(
                self.sites if sites is None else sites, [], {}, self.coordinates, {},
                checkpoint_store=store, runtime_stats=stats,
                prefetch_workers=2, prefetch_depth=2, prefetch_memory_mib=384,
            )

    def test_cold_warm_reference_parity_and_lazy_sources(self):
        reference = self.run_assessment()
        cold_stats = runtime.RuntimeStats()
        cold = self.run_assessment(self.store, stats=cold_stats)
        self.assertEqual(reference, cold)
        self.assertEqual(cold_stats.counts["groups_generated"], 2)
        warm_stats = runtime.RuntimeStats()
        with mock.patch.object(s6c, "ExactSurfaceIndex", side_effect=AssertionError("warm source opened")):
            warm = self.run_assessment(self.store, stats=warm_stats)
        self.assertEqual(reference, warm)
        self.assertEqual(warm_stats.counts, {"groups_reused": 2})

    def test_interruption_preserves_finished_group_and_resumes_in_order(self):
        self.fail_second = True
        with self.assertRaisesRegex(RuntimeError, "injected second-group"):
            self.run_assessment(self.store)
        self.fail_second = False
        self.distance_calls.clear()
        stats = runtime.RuntimeStats()
        resumed = self.run_assessment(self.store, stats=stats)
        self.assertEqual(self.distance_calls, ["S1"])
        self.assertEqual([row["settlement_id"] for row in resumed[0]], ["S0", "S1"])
        self.assertEqual({key: value for key, value in stats.counts.items()
                          if not key.startswith("assessment_groups.")},
                         {"groups_reused": 1, "groups_generated": 1})
        self.assertEqual(stats.counts["assessment_groups.completed"], 1)
        self.assertEqual(resumed, self.run_assessment())

    def test_one_changed_site_recomputes_only_its_group(self):
        self.run_assessment(self.store)
        self.distance_calls.clear()
        changed = [self.sites[0], dataclasses.replace(self.sites[1], x=130.1)]
        actual = self.run_assessment(self.store, sites=changed)
        self.assertEqual(self.distance_calls, ["S1"])
        self.assertEqual(actual, self.run_assessment(sites=changed))

    def test_corrupt_checkpoint_is_recomputed(self):
        self.run_assessment(self.store)
        next(self.store.directory.glob("*.json")).write_text("truncated", encoding="utf-8")
        self.distance_calls.clear()
        actual = self.run_assessment(self.store)
        self.assertEqual(len(self.distance_calls), 1)
        self.assertEqual(actual, self.run_assessment())

    def test_memory_budget_caps_existing_prefetch_and_rejects_invalid_values(self):
        worker = s6c.RasterGroupPrefetcher([], {}, object(), object(), workers=8, depth=8, memory_mib=256)
        try:
            self.assertEqual((worker.workers, worker.depth), (1, 1))
        finally:
            worker.close()
        with self.assertRaises(ValueError):
            s6c.RasterGroupPrefetcher([], {}, object(), object(), memory_mib=128)


class Stage6CReleaseReceiptTests(unittest.TestCase):
    def test_valid_full_receipt_skips_analysis_and_corruption_fails_closed(self):
        with FixtureDirectory(dir=FIXTURE_ROOT) as temporary, contextlib.ExitStack() as stack:
            root = Path(temporary)
            out, work = root / "outputs", root / "runtime"
            out.mkdir()
            marker = out / "validated.json"
            marker.write_text("{}", encoding="utf-8")
            runtime.save_receipt(work / "stage6c-release.receipt.json", "test-identity", out,
                                 [marker], {"return_code": 0, "status": "PASS"})
            for name in ("OUT_DIR", "OUT_DB", "OUT_GPKG", "EXPORT_DIR", "WORK_DIR"):
                stack.enter_context(mock.patch.object(s6c, name, getattr(s6c, name)))
            stack.enter_context(mock.patch.object(s6c, "verify_sources", return_value=([], {}, {})))
            stack.enter_context(mock.patch.object(s6c, "generation_identity", return_value="test-identity"))
            stack.enter_context(mock.patch.object(s6c, "transform_score_self_check", side_effect=RuntimeError("must analyse")))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(s6c.main(["--output-dir", str(out), "--work-dir", str(work)]), 0)
                marker.write_text("corrupt", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "must analyse"):
                    s6c.main(["--output-dir", str(out), "--work-dir", str(work)])


class PopulationReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = FixtureDirectory(dir=FIXTURE_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.output = self.root / "source.sqlite", self.root / "population.sqlite"
        with contextlib.closing(sqlite3.connect(self.source)) as connection:
            connection.execute("CREATE TABLE source(value INTEGER)")
            connection.execute("INSERT INTO source VALUES (1)")
            connection.commit()
        self.build_count = 0
        self.fail_export = False
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(s6d, "combined_rule_fingerprint", return_value="fixture-rules"))
        stack.enter_context(mock.patch.object(s6d.runtime, "implementation_identity", return_value={"fixture": "v1"}))
        stack.enter_context(mock.patch.object(s6d, "_build_complete_database", side_effect=self.fake_build))
        stack.enter_context(mock.patch.object(s6d, "_validate_builder_invariants", side_effect=lambda connection, run_id: {
            "status": "PASS", "count": connection.execute("SELECT COUNT(*) FROM result").fetchone()[0]}))
        stack.enter_context(mock.patch.object(s6d, "_write_summary", side_effect=self.write_summary))
        stack.enter_context(mock.patch.object(s6d, "_write_review_csv", side_effect=self.write_review))

    def fake_build(self, source, output, *, expected_active_sites, expected_source_identity=None, **execution_options):
        self.build_count += 1
        with contextlib.closing(sqlite3.connect(output)) as connection:
            connection.execute("DROP TABLE IF EXISTS result")
            connection.execute("CREATE TABLE result(value INTEGER)")
            connection.execute("INSERT INTO result VALUES (7)")
            connection.commit()
        return {"status": "PASS", "run_id": "SYNTHETIC", "source_site_count": 1,
                "site_pool_count": 1, "preliminary_normal_supported_humans": 7,
                "output_database": str(output)}

    def write_summary(self, connection, run_id, path, validation):
        result = {"status": "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON", "humans": 7}
        path.write_text(json.dumps(result), encoding="utf-8")
        return result

    def write_review(self, connection, run_id, path):
        if self.fail_export:
            raise RuntimeError("injected export interruption")
        path.write_text("humans\n7\n", encoding="utf-8")

    def test_cold_warm_and_explicit_reference(self):
        first = s6d.build(self.source, self.output, expected_active_sites=1)
        warm_stats = runtime.RuntimeStats()
        second = s6d.build(self.source, self.output, expected_active_sites=1, runtime_stats=warm_stats)
        self.assertEqual(first, second)
        self.assertEqual(self.build_count, 1)
        self.assertEqual(warm_stats.counts, {"releases_reused": 1})
        reference = s6d.build(self.source, self.output, expected_active_sites=1, reuse=False)
        self.assertEqual(reference, first)
        self.assertEqual(self.build_count, 2)

    def test_export_interruption_resumes_completed_database(self):
        self.fail_export = True
        with self.assertRaisesRegex(RuntimeError, "export interruption"):
            s6d.build(self.source, self.output, expected_active_sites=1)
        self.fail_export = False
        stats = runtime.RuntimeStats()
        result = s6d.build(self.source, self.output, expected_active_sites=1, runtime_stats=stats)
        self.assertEqual(self.build_count, 1)
        self.assertEqual(result["preliminary_normal_supported_humans"], 7)
        self.assertEqual(stats.counts, {"databases_reused": 1})

    def test_changed_source_invalidates_both_receipts(self):
        s6d.build(self.source, self.output, expected_active_sites=1)
        with contextlib.closing(sqlite3.connect(self.source)) as connection:
            connection.execute("UPDATE source SET value=2")
            connection.commit()
        s6d.build(self.source, self.output, expected_active_sites=1)
        self.assertEqual(self.build_count, 2)

    def test_corrupt_export_rebuilds_exports_only(self):
        first = s6d.build(self.source, self.output, expected_active_sites=1)
        self.output.with_suffix(".review.csv").write_text("corrupt", encoding="utf-8")
        second = s6d.build(self.source, self.output, expected_active_sites=1)
        self.assertEqual(self.build_count, 1)
        self.assertEqual(second, first)

    def test_implementation_and_scope_changes_invalidate(self):
        s6d.build(self.source, self.output, expected_active_sites=1)
        with mock.patch.object(s6d.runtime, "implementation_identity", return_value={"fixture": "v2"}):
            s6d.build(self.source, self.output, expected_active_sites=1)
        s6d.build(self.source, self.output, expected_active_sites=2)
        self.assertEqual(self.build_count, 3)

    def test_alias_paths_rejected_before_any_writes(self):
        with self.assertRaises(ValueError):
            s6d.build(self.source, self.source)
        with self.assertRaises(ValueError):
            s6d.build(self.source, self.output, summary_json=self.source)
        self.assertEqual(self.build_count, 0)

    def test_source_drift_before_install_retains_prior_database(self):
        binding = runtime.file_identity(self.source)
        self.output.write_bytes(b"prior validated release")
        candidate = self.root / ".candidate.sqlite"
        candidate.write_bytes(b"new candidate")
        with contextlib.closing(sqlite3.connect(self.source)) as connection:
            connection.execute("UPDATE source SET value=3")
            connection.commit()
        with self.assertRaisesRegex(RuntimeError, "prior output was retained"):
            s6d._install_complete_database(candidate, self.output, self.source, binding)
        self.assertEqual(self.output.read_bytes(), b"prior validated release")
        self.assertFalse(candidate.exists())


if __name__ == "__main__":
    unittest.main()
