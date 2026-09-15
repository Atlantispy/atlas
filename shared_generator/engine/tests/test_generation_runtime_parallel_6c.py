"""Synthetic real-kernel assessment concurrency, ordering and recovery tests."""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np
import shapely
from shapely.geometry import LineString, Point

import build_stage6c_100m as s6c
import generation_runtime as runtime


class FixtureDirectory(tempfile.TemporaryDirectory):
    def cleanup(self):
        if os.name == "nt" and not self.name.startswith("\\\\?\\"):
            self.name = "\\\\?\\" + str(Path(self.name).resolve())
        super().cleanup()


class ParallelAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = FixtureDirectory(dir=Path(__file__).resolve().parents[2])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main_thread = threading.get_ident()
        self.lock = threading.Lock()
        self.active = self.peak_active = self.prepared = self.peak_uncommitted = 0
        self.computed = []
        self.compute_threads = []
        self.read_threads = []
        self.commits = []
        self.close_active = []
        self.fail_site = None
        self.cancel = threading.Event()
        self.cancel_on_commit = False
        self.fail_commit = False
        self.sites = []
        self.coordinates = []
        self.profiles = []
        self.links = {}
        for index, (form, domain) in enumerate((
            ("AGRARIAN_SETTLEMENT", "SURFACE"),
            ("SURFACE_LAGOON_SETTLEMENT", "SURFACE"),
            ("WETLAND_STILT_OR_CHANNEL_SETTLEMENT", "WETLAND_INTERIOR"),
            ("AGRARIAN_SETTLEMENT", "SURFACE"),
        )):
            site = s6c.Site(
                settlement_id=f"S{index}", x=10.0 + index * 120.0, y=10.0,
                barony_id=1, active_location=int(index < 3),
                active_settlement=int(index < 3), added_identity=0,
                conditionality=None, functional_tier="FT0_HAUS_PRINCIPAL_SITE",
                realised_form=form, form_family="FIXTURE", vertical_domain=domain,
                ordinary_human=1,
            )
            self.sites.append(site)
            self.coordinates.append({
                "settlement_id": site.settlement_id,
                "original_display_x_km": site.x, "original_display_y_km": site.y,
                "coordinate_semantics_code": "SYNTHETIC",
                "coordinate_value_resolution_km": 1.0,
                "coordinate_precision_basis": "TEST", "anchor_status": "TEST",
                "provisional_anchor": index % 2, "horizontal_uncertainty_shape": "TEST",
                "horizontal_uncertainty_radius_km": 1.0,
                "vertical_uncertainty_status": "TEST", "footprint_status": "TEST",
            })
            if index < 3:
                combo = {"haus_id": "TEST", "realised_settlement_form": form,
                         "effective_vertical_domain": domain, "site_count": 1}
                with mock.patch.object(s6c.rules, "observed_profile_combinations", return_value=[combo]):
                    profile = s6c.rules.profile_catalog_rows(None)[0]
                self.profiles.append(profile)
                self.links[site.settlement_id] = {
                    "profile_id": profile["profile_id"], "owner_haus_id": "TEST",
                    "owner_assignment_basis": "SYNTHETIC",
                }
        owner = self

        class Raster:
            def __init__(self, _authority):
                pass

            def read_block(self, row, col, height, width):
                with owner.lock:
                    owner.read_threads.append(threading.get_ident())
                    owner.prepared += 1
                    owner.peak_uncommitted = max(owner.peak_uncommitted, owner.prepared)
                rr, cc = np.indices((height, width))
                terrain = ((rr + row) * 0.125 + (cc + col) * 0.375).astype(np.float32)
                zeros = np.zeros(terrain.shape, dtype=np.uint8)
                return {"terrain": terrain, "slope": ((rr + cc) % 19).astype(np.float32),
                        "sea": zeros.copy(), "moor": zeros.copy(), "seren": zeros.copy(),
                        "flood": zeros.astype(np.float32), "wetland": zeros.copy(),
                        "flood_exposure": ((rr % 3) * 0.125).astype(np.float32)}

            def close(self):
                owner.close_active.append(owner.active)

        class Vectors(s6c.VectorStack):
            def __init__(self, mode):
                self.query_mode = mode
                self.hydrology_composition = {"synthetic": 1}
                river = LineString([(0, 12), (500, 12)])
                minor = LineString([(12, 0), (12, 500)])
                lake = Point(130, 10).buffer(0.20)
                coast = LineString([(0, 0), (500, 0)])
                self.coast_cover_polygons = []
                for name, geoms in {
                    "major_index_tree": [river], "minor_tree": [minor],
                    "special_tree": [lake], "permanent_lake_tree": [lake],
                    "seasonal_lake_tree": [Point(20, 20).buffer(0.1)],
                    "managed_special_tree": [lake], "coast_index_tree": [coast],
                    "active_index_tree": [river, minor, lake, coast],
                    "perennial_index_tree": [river, minor, lake],
                }.items():
                    setattr(self, name, shapely.STRtree(geoms))

            def candidate_distance_batch(self, xs, ys, sites):
                with owner.lock:
                    owner.active += 1
                    owner.peak_active = max(owner.peak_active, owner.active)
                    owner.compute_threads.append(threading.get_ident())
                try:
                    # First completion is deliberately later than the second;
                    # ordering must come from the coordinator, not luck.
                    time.sleep(0.06 if sites[0].settlement_id == "S0" else 0.02)
                    if owner.fail_site == sites[0].settlement_id:
                        raise RuntimeError("injected assessment failure")
                    result = super().candidate_distance_batch(xs, ys, sites)
                    owner.computed.append(sites[0].settlement_id)
                    return result
                finally:
                    with owner.lock:
                        owner.active -= 1

        class Store(runtime.CheckpointStore):
            def save(self, key, payload):
                if owner.fail_commit:
                    raise RuntimeError("injected checkpoint commit failure")
                owner.commits.append((payload["site_ids"], threading.get_ident()))
                super().save(key, payload)
                with owner.lock:
                    owner.prepared -= 1
                if owner.cancel_on_commit:
                    owner.cancel.set()

        self.store = Store(self.root / "groups", "synthetic-assessment-v1")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(s6c, "RasterStack", Raster))
        stack.enter_context(mock.patch.object(s6c, "VectorStack", Vectors))
        stack.enter_context(mock.patch.object(s6c, "ExactSurfaceIndex", side_effect=lambda *_: mock.Mock(
            rasterize_window=lambda row, col, height, width: np.ones((height, width), dtype=np.int32))))
        stack.enter_context(mock.patch.object(s6c, "source_fingerprint_identity", return_value={"fixture": "v1"}))

    def run_assessment(self, *, workers=4, memory=1024, store=None, cancel=None, stats=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return s6c.assess_all_sites(
                self.sites, self.profiles, self.links, self.coordinates, {},
                workers=workers, memory_budget_mb=memory, checkpoint_store=store,
                cancel_event=cancel, runtime_stats=stats,
                prefetch_workers=1, prefetch_depth=1, prefetch_memory_mib=256,
            )

    def reset_observations(self):
        self.active = self.peak_active = self.prepared = self.peak_uncommitted = 0
        self.computed.clear()
        self.compute_threads.clear()
        self.read_threads.clear()
        self.commits.clear()
        self.close_active.clear()

    def test_real_scoring_parallel_parity_order_and_reader_ownership(self):
        serial = self.run_assessment(workers=1)
        # Captured against the preserved pre-parallel builder with these
        # synthetic sources; covers real profile scoring and one exception.
        self.assertEqual(hashlib.sha256(s6c.canonical_json(serial).encode()).hexdigest(),
                         "9903fe4f0dbeb816da351b180f353b771d9b9e62778cd085489afecd381b6493")
        self.assertEqual(set(self.compute_threads), {self.main_thread})
        self.assertIsNotNone(serial[0][0]["capacity_support_score"])
        self.assertTrue(serial[1], "fixture must cover meaningful review exceptions")
        self.reset_observations()
        with mock.patch.object(s6c, "RasterGroupPrefetcher", side_effect=AssertionError("nested prefetch pool")):
            parallel = self.run_assessment(store=self.store)
        self.assertEqual(s6c.canonical_json(serial), s6c.canonical_json(parallel))
        self.assertEqual([row["settlement_id"] for row in parallel[0]], ["S0", "S1", "S2", "S3"])
        self.assertGreater(self.peak_active, 1)
        self.assertGreater(len(set(self.compute_threads)), 1)
        self.assertNotIn(self.main_thread, self.compute_threads)
        self.assertEqual(set(self.read_threads), {self.main_thread})
        self.assertEqual(self.commits, [([f"S{i}"], self.main_thread) for i in range(4)])
        self.assertNotEqual(self.computed[0], "S0")
        self.assertEqual(self.close_active, [0])

    def test_budget_bounds_preparation_and_worker_admission(self):
        stats = runtime.RuntimeStats()
        self.run_assessment(workers=8, memory=512, store=self.store, stats=stats)
        self.assertEqual(self.peak_active, 2)
        self.assertLessEqual(self.peak_uncommitted, 2)
        self.assertEqual(self.prepared, 0)
        self.assertEqual(stats.counts["assessment_groups.worker_limit"], 2)
        self.assertEqual(stats.counts["assessment_groups.peak_active_workers"], 2)
        self.assertEqual(stats.counts["assessment_groups.completed"], 4)

    def test_private_prepared_arrays_are_read_only_and_unchanged(self):
        original = s6c._assess_prepared_group
        checked = []

        def inspect(prepared, *args, **kwargs):
            arrays = (*prepared.candidate_rows, *prepared.candidate_cols,
                      *prepared.raster.values(), prepared.barony_grid)
            self.assertTrue(all(not array.flags.writeable for array in arrays))
            before = [array.tobytes() for array in arrays]
            result = original(prepared, *args, **kwargs)
            self.assertEqual(before, [array.tobytes() for array in arrays])
            checked.append(prepared.group_index)
            return result

        with mock.patch.object(s6c, "_assess_prepared_group", side_effect=inspect):
            self.run_assessment()
        self.assertEqual(sorted(checked), [1, 2, 3, 4])

    def test_budget_one_slot_runs_on_caller(self):
        self.run_assessment(workers=8, memory=256, store=self.store)
        self.assertEqual(self.peak_active, 1)
        self.assertEqual(set(self.compute_threads), {self.main_thread})
        self.assertLessEqual(self.peak_uncommitted, 1)

    def test_serial_budget_cannot_silently_increase_or_start_prefetch(self):
        stats = runtime.RuntimeStats()
        with mock.patch.object(s6c, "RasterGroupPrefetcher", side_effect=AssertionError("unbudgeted prefetch")):
            self.run_assessment(workers=1, memory=256, store=self.store, stats=stats)
        self.assertEqual(set(self.read_threads), {self.main_thread})
        self.assertEqual(stats.counts["assessment_groups.memory_budget_bytes"], 256 * 1024 * 1024)

    def test_below_group_estimate_rejected_before_any_preload_even_serial(self):
        with mock.patch.object(s6c, "RASTER_GROUP_ESTIMATED_BYTES", 512 * 1024 * 1024), \
                mock.patch.object(s6c, "ExactSurfaceIndex", side_effect=AssertionError("underbudget source open")):
            for workers in (1, 2):
                with self.subTest(workers=workers), self.assertRaisesRegex(ValueError, "cannot admit one"):
                    self.run_assessment(workers=workers, memory=512)

    def test_worker_failure_joins_and_resumes_saved_prefix(self):
        self.fail_site = "S1"
        with self.assertRaisesRegex(RuntimeError, "injected assessment failure"):
            self.run_assessment(store=self.store)
        self.assertEqual(self.commits, [(["S0"], self.main_thread)])
        self.assertEqual(self.close_active, [0])
        self.fail_site = None
        self.reset_observations()
        resumed = self.run_assessment(store=self.store)
        self.assertNotIn("S0", self.computed)
        reference = self.run_assessment(workers=1)
        self.assertEqual(s6c.canonical_json(resumed), s6c.canonical_json(reference))

    def test_commit_failure_joins_workers_without_saved_completion(self):
        self.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, "injected checkpoint commit failure"):
            self.run_assessment(store=self.store)
        self.assertEqual(self.close_active, [0])
        self.assertFalse(list(self.store.directory.glob("*.json")))

    def test_cancellation_keeps_only_committed_prefix_and_resume_is_exact(self):
        self.cancel_on_commit = True
        with self.assertRaises(runtime.GenerationCancelled):
            self.run_assessment(store=self.store, cancel=self.cancel)
        self.assertEqual(self.commits, [(["S0"], self.main_thread)])
        self.assertEqual(self.close_active, [0])
        self.cancel_on_commit = False
        self.cancel.clear()
        self.reset_observations()
        resumed = self.run_assessment(store=self.store)
        self.assertNotIn("S0", self.computed)
        self.assertEqual(s6c.canonical_json(resumed), s6c.canonical_json(self.run_assessment(workers=1)))

    def test_pre_cancelled_run_opens_no_sources(self):
        self.cancel.set()
        with mock.patch.object(s6c, "ExactSurfaceIndex", side_effect=AssertionError("cancelled source open")):
            with self.assertRaises(runtime.GenerationCancelled):
                self.run_assessment(cancel=self.cancel)

    def test_corruption_recomputes_one_group_and_warm_run_opens_no_sources(self):
        reference = self.run_assessment(store=self.store)
        next(self.store.directory.glob("*.json")).write_text("corrupt", encoding="utf-8")
        self.reset_observations()
        repaired = self.run_assessment(store=self.store)
        self.assertEqual(len(self.computed), 1)
        self.assertEqual(s6c.canonical_json(reference), s6c.canonical_json(repaired))
        with mock.patch.object(s6c, "ExactSurfaceIndex", side_effect=AssertionError("warm source open")):
            self.assertEqual(reference, self.run_assessment(store=self.store))

    def test_invalid_controls_fail_before_sources(self):
        with mock.patch.object(s6c, "ExactSurfaceIndex", side_effect=AssertionError("invalid source open")):
            for workers, memory in ((0, 512), (True, 512), (2, 255), (2, True)):
                with self.subTest(workers=workers, memory=memory), self.assertRaises(ValueError):
                    self.run_assessment(workers=workers, memory=memory)
            with self.assertRaises(TypeError):
                self.run_assessment(cancel=object())


if __name__ == "__main__":
    unittest.main()
