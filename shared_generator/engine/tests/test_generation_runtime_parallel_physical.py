"""Physical site scheduling: isolated sources, exact kernels and ordered commits."""
from __future__ import annotations

from contextlib import ExitStack, closing, contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from rasterio import Affine
from rasterio.windows import Window
import shapely

import build_stage6c5r_physical_10m as sr
from generation_runtime import GenerationCancelled, RuntimeStats
from stage6c5r_climate import ClimateWindow


def work_item(index):
    return sr.SiteWork(SimpleNamespace(
        index=index, semantic_key=f"{index + 100:064x}", disposition="COMPLETE_2D_REFINEMENT",
        site=SimpleNamespace(settlement_id=f"S{index}", x=1.05 + index * .1, y=1.05,
                             functional_tier="FT0_HAUS_PRINCIPAL_SITE"),
    ), 10, 10 + index, 9, 9 + index, 1, 1, f"{index + 1:064x}")


class FakeRasters:
    def __init__(self, *_):
        self.owner = threading.get_ident()
        self.reads = []
        self.closed = False
        self.terrain = SimpleNamespace(descriptor={"root_hash": "a" * 64}, read_block=self.terrain_read)

    def terrain_read(self, row, col, height, width):
        if threading.get_ident() != self.owner:
            raise AssertionError("Source raster handle escaped its coordinator")
        self.reads.append((row, col, height, width))
        rr, cc = np.meshgrid(np.arange(row, row + height), np.arange(col, col + width), indexing="ij")
        return (200.0 - rr * .4 - cc * .2).astype(np.float32)

    def read_block(self, *window):
        terrain = self.terrain_read(*window)
        mask = np.zeros(terrain.shape, dtype=np.uint8)
        return {"terrain": terrain, "sea": mask.copy(), "seren": mask.copy(),
                "wetland": mask.copy(), "flood_exposure": mask.astype(np.float32)}

    def close(self):
        self.closed = True


class FakeClimate:
    def __init__(self):
        self.owner = threading.get_ident()
        self.reads = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read_window(self, window):
        if threading.get_ident() != self.owner:
            raise AssertionError("Climate archive handle escaped its coordinator")
        self.reads.append(window)
        shape = (12, int(window.height), int(window.width))
        return ClimateWindow(
            np.full(shape, 80, dtype=np.float32), np.full(shape, 25, dtype=np.float32),
            np.zeros(shape, dtype=np.float32), np.full(shape, 10, dtype=np.float32),
            np.ones(shape[1:], dtype=bool), Affine.identity(), window,
            {"source": "synthetic-climate", "status": "FIXTURE_NOT_CANON"},
        )


@contextmanager
def small_grid():
    with ExitStack() as stack:
        for name, value in (("WINDOW_PARENT_CELLS", 2), ("FINE_CELLS", 20),
                            ("ANALYSIS_PARENT_CELLS", 4), ("ANALYSIS_FINE_CELLS", 40),
                            ("SUPPORT_PARENT_HALO", 1)):
            stack.enter_context(patch.object(sr, name, value))
        yield


def empty_indexes():
    topology = SimpleNamespace(carrier_baronies=np.ones((30, 30), dtype=np.int32),
                               partial_carriers_by_row={})
    vectors = SimpleNamespace(special_geoms=[], managed_special_geoms=[])
    for stem in ("major", "minor", "permanent_lake"):
        setattr(vectors, stem + "_geoms", [])
        setattr(vectors, stem + "_props", [])
        setattr(vectors, stem + "_tree", shapely.STRtree([]))
    return topology, vectors, SimpleNamespace()


class PreparedPhysicalTests(unittest.TestCase):
    def test_preload_windows_exact_and_raster_copies_independent(self):
        work, live, climate = work_item(0), FakeRasters(), FakeClimate()
        with small_grid():
            prepared, prepared_climate = sr.prepare_physical_inputs(work, live, climate)
            window = (work.analysis_row0, work.analysis_col0, 4, 4)
            np.testing.assert_array_equal(prepared.terrain.read_block(*window), live.terrain_read(*window))
            values = prepared.read_block(*window)
            values["terrain"][:] = -999
            self.assertFalse(np.any(prepared.core["terrain"] == -999))
            np.testing.assert_array_equal(prepared_climate.read_window(climate.reads[0]).precipitation_mm,
                                          climate.read_window(climate.reads[0]).precipitation_mm)
            with self.assertRaises(ValueError):
                prepared_climate.read_window(Window(0, 0, 4, 4))

    def test_real_physical_kernels_serial_parallel_bit_exact_and_artifacts_identical(self):
        topology, vectors, profiles = empty_indexes()
        vectors.minor_geoms = [shapely.LineString([(1.01, .95), (1.25, 1.25)])]
        vectors.minor_props = [{"minor_id": "synthetic-channel", "tier_code": 2,
                                "persistence": "PERENNIAL", "contributing_area_km2": 1.0}]
        vectors.minor_tree = shapely.STRtree(vectors.minor_geoms)
        items = [(index, work_item(index)) for index in range(2)]
        snapshots = []
        with small_grid(), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for workers in (1, 2):
                output = root / str(workers)
                output.mkdir()
                captured = []
                with closing(sr.physical_site_results(
                    items, FakeRasters(), topology, vectors, profiles, FakeClimate(), output,
                    workers=workers, memory_budget_mb=1024, stats=RuntimeStats(),
                )) as results:
                    for position, work, checkpoint, arrays, private in results:
                        projected = dict(checkpoint)
                        projected.pop("completed_utc")
                        self.assertGreater(checkpoint["metrics"]["physically_admissible_route_count"], 0)
                        sr.install_private_site(output, private, checkpoint)
                        captured.append((projected, {key: value.copy() for key, value in arrays.items()}))
                snapshots.append(captured)
                self.assertFalse(list(output.glob(".physical-*")))
            for serial, parallel in zip(*snapshots):
                self.assertEqual(serial[0], parallel[0])
                self.assertEqual(set(serial[1]), set(sr.array_specs()))
                for key in serial[1]:
                    self.assertEqual(serial[1][key].dtype, parallel[1][key].dtype)
                    self.assertEqual(serial[1][key].tobytes(), parallel[1][key].tobytes(), key)


class SchedulingTests(unittest.TestCase):
    def exercise(self, workers, budget, *, fail=None, cancel=False, abandon=False):
        owner = threading.get_ident()
        lock, active, peak = threading.Lock(), 0, 0
        started, finished, commits, reference = [], [], [], []
        cancel_event = threading.Event()

        def compute(work, rasters, topology, vectors, profiles, climate, output, verify_reference):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                started.append(work.candidate.index)
                reference.append((work.candidate.index, verify_reference))
            try:
                self.assertNotEqual(output, public)
                self.assertTrue(output.parent.parent.samefile(public))
                # Both array-only adapters are safe away from the source owner.
                values = rasters.read_block(work.analysis_row0, work.analysis_col0, 4, 4)["terrain"]
                climate.read_window(Window(work.analysis_col0, work.analysis_row0, 4, 4))
                time.sleep(.08 if work.candidate.index == 0 else .02)
                if work.candidate.index == fail:
                    sr.atomic_json(output / "failures" / f"S{fail}.json", {"status": "FAIL_CLOSED"})
                    raise RuntimeError("injected physical failure")
                if cancel and work.candidate.index == 0:
                    cancel_event.set()
                return {"position": work.candidate.index}, {"elevation": values}
            finally:
                with lock:
                    active -= 1
                    finished.append(work.candidate.index)

        with tempfile.TemporaryDirectory() as directory, small_grid(), patch.object(sr, "site_result", side_effect=compute):
            public = Path(directory)
            rasters, climate = FakeRasters(), FakeClimate()
            results = sr.physical_site_results(
                [(i, work_item(i)) for i in range(5)], rasters, object(), object(), object(), climate,
                public, workers=workers, memory_budget_mb=budget, stats=RuntimeStats(), cancel_event=cancel_event,
            )
            error = None
            try:
                with closing(results):
                    for position, work, checkpoint, arrays, private in results:
                        self.assertEqual(threading.get_ident(), owner)
                        commits.append(position)
                        # No more than the bounded window may have been loaded.
                        self.assertLessEqual(len(climate.reads) - len(commits), min(workers, budget // 512) - 1)
                        if abandon:
                            break
            except (sr.PhysicalSiteComputationError, GenerationCancelled) as caught:
                error = caught
            self.assertEqual(active, 0)
            self.assertEqual(sorted(started), sorted(finished))
            self.assertFalse(list(public.glob(".physical-*")))
            if fail is not None:
                self.assertEqual(json.loads((public / "failures" / f"S{fail}.json").read_text()), {"status": "FAIL_CLOSED"})
            return peak, commits, started, reference, error

    def test_workers_overlap_and_results_commit_in_order(self):
        peak, commits, _, reference, error = self.exercise(3, 1536)
        self.assertEqual(peak, 3)
        self.assertEqual(commits, list(range(5)))
        self.assertEqual(sorted(reference), [(i, i == 0) for i in range(5)])
        self.assertIsNone(error)

    def test_memory_budget_caps_admission(self):
        peak, commits, *_ = self.exercise(8, 1024)
        self.assertEqual(peak, 2)
        self.assertEqual(commits, list(range(5)))

    def test_one_worker_reference_runs_without_overlap(self):
        peak, commits, *_ = self.exercise(1, 1024)
        self.assertEqual(peak, 1)
        self.assertEqual(commits, list(range(5)))

    def test_failure_joins_workers_preserves_diagnostic_and_stops_commits(self):
        _, commits, started, _, error = self.exercise(2, 1024, fail=0)
        self.assertIsInstance(error, sr.PhysicalSiteComputationError)
        self.assertEqual(commits, [])
        self.assertEqual(sorted(started), [0, 1])

    def test_cancellation_joins_without_committing(self):
        _, commits, started, _, error = self.exercise(2, 1024, cancel=True)
        self.assertIsInstance(error, GenerationCancelled)
        self.assertEqual(commits, [])
        self.assertEqual(sorted(started), [0, 1])

    def test_consumer_abandonment_joins_before_scratch_removal(self):
        _, commits, started, _, error = self.exercise(2, 1024, abandon=True)
        self.assertEqual(commits, [0])
        self.assertEqual(sorted(started), [0, 1])
        self.assertIsNone(error)

    def test_invalid_admission_rejected_before_output_or_sources(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sr.s6c, "verify_sources") as verify:
            output = Path(directory) / "must-not-exist"
            for kwargs in ({"workers": 0}, {"workers": 65}, {"workers": True},
                           {"memory_budget_mb": 511}, {"memory_budget_mb": True}):
                with self.assertRaises(ValueError):
                    sr.run(output, "FT0", **kwargs)
            self.assertFalse(output.exists())
            verify.assert_not_called()


class PublicationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows extended private-path regression")
    def test_private_staging_does_not_reduce_supported_public_path_length(self):
        topology, vectors, profiles = empty_indexes()
        with small_grid(), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / ("p" * max(1, 140 - len(str(root)) - 1))
            output.mkdir()
            with closing(sr.physical_site_results(
                [(0, work_item(0))], FakeRasters(), topology, vectors, profiles, FakeClimate(), output,
                workers=1, memory_budget_mb=512, stats=RuntimeStats(),
            )) as results:
                for _, _, checkpoint, arrays, private in results:
                    self.assertTrue(str(private).startswith("\\\\?\\"))
                    relative = Path(checkpoint["bundle_relative_path"])
                    temporary_frame = (relative.parent / ("." + relative.name + "." + "a" * 32 + ".tmp")
                                       / "frames" / ("000000-" + "a" * 16 + ".zst"))
                    self.assertLess(len(str(output / temporary_frame)), 260)
                    self.assertGreaterEqual(len(str(private / temporary_frame).removeprefix("\\\\?\\")), 260)
                    for key in ("bundle_relative_path", "route_relative_path", "review_map_relative_path"):
                        self.assertFalse(Path(checkpoint[key]).is_absolute())
                        self.assertNotIn("\\\\?\\", checkpoint[key])
                    sr.install_private_site(output, private, checkpoint)
                    self.assertEqual(sr.arrays_digest(arrays), checkpoint["array_digest"])
            self.assertFalse(list(output.glob(".physical-*")))

    def test_corrupted_private_artifact_blocks_bundle_publication(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sr.s6c5, "install_private_bundle") as bundle:
            root = Path(directory)
            private = root / "private"
            private.mkdir()
            (private / "route").write_bytes(b"route")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                sr.install_private_site(root / "public", private, {
                    "route_relative_path": "route", "route_sha256": "wrong",
                })
            bundle.assert_not_called()

    def test_artifact_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "escaped"):
                sr.install_private_site(root / "public", root / "private", {
                    "route_relative_path": "../escape", "route_sha256": "unused",
                })


class RunLifecycleTests(unittest.TestCase):
    @contextmanager
    def fixture(self, output, *, fail_write=False, source_changed=False):
        owner = threading.get_ident()
        events = []
        works = [work_item(index) for index in range(3)]
        candidates = [work.candidate for work in works]

        class CallerArray:
            def __init__(self, name, values):
                self.name, self.values = name, values

            def __getitem__(self, index):
                self.check()
                return self.values[index]

            def check(self):
                if threading.get_ident() != owner:
                    raise AssertionError("Public store accessed by a worker")

            def __setitem__(self, index, value):
                self.check()
                events.append((self.name, index, int(value) if self.name == "complete" else None))
                if fail_write and self.name == "field":
                    raise OSError("injected public write failure")
                self.values[index] = value

        group = {"field": CallerArray("field", np.zeros((3, 2, 2), dtype=np.float32)),
                 "site_complete": CallerArray("complete", np.ones(3, dtype=np.uint8))}
        original_atomic = sr.atomic_json

        def atomic(path, value):
            if Path(path).parent == output / "checkpoints":
                self.assertEqual(threading.get_ident(), owner)
                events.append(("checkpoint", int(value["settlement_id"][1:]), None))
            return original_atomic(path, value)

        def compute(work, *args, **kwargs):
            time.sleep(.04 if work.candidate.index == 0 else .01)
            arrays = {"field": np.full((2, 2), work.candidate.index + .5, dtype=np.float32)}
            return {"settlement_id": work.candidate.site.settlement_id,
                    "array_digest": sr.arrays_digest(arrays),
                    "metrics": {"pilot_site_gate_pass": True, "incomplete_quarantined_route_count": 0}}, arrays

        def install(*args):
            self.assertEqual(threading.get_ident(), owner)
            events.append(("install", int(args[2]["settlement_id"][1:]), None))

        def climate_guard(_):
            self.assertEqual(threading.get_ident(), owner)
            if source_changed:
                raise RuntimeError("Climate archive changed during the run")

        with ExitStack() as stack:
            connection = MagicMock()
            connection.execute.return_value.fetchone.return_value = ("ok",)
            sql = stack.enter_context(patch.object(sr.s6c5, "sqlite_readonly"))
            sql.return_value.__enter__.return_value = connection
            stack.enter_context(patch.object(sr.s6c5, "load_candidates", return_value=candidates))
            stack.enter_context(patch.object(sr.s6c5, "capture_source_guards", return_value={}))
            stack.enter_context(patch.object(sr.s6c5, "require_source_guards"))
            stack.enter_context(patch.object(sr.s6c5, "require_terrain_identity"))
            stack.enter_context(patch.object(sr.s6c5, "runtime_implementation", return_value={"code": "fixture"}))
            stack.enter_context(patch.object(sr.s6c, "verify_sources", return_value=([], {"root_hash": "a" * 64}, {})))
            stack.enter_context(patch.object(sr.s6c, "ExactSurfaceIndex", return_value=object()))
            stack.enter_context(patch.object(sr.s6c, "VectorStack", return_value=SimpleNamespace(major_geoms=[], major_props=[])))
            stack.enter_context(patch.object(sr.s6c, "RasterStack", FakeRasters))
            stack.enter_context(patch.object(sr, "ActiveMajorBedProfiles", return_value=SimpleNamespace(validate_axes=lambda _: {})))
            stack.enter_context(patch.object(sr, "C1MonthlyClimateReader", FakeClimate))
            stack.enter_context(patch.object(sr, "EXPECTED_ALL", len(works)))
            stack.enter_context(patch.object(sr, "scope_candidates", return_value=candidates))
            stack.enter_context(patch.object(sr, "source_identity", return_value={}))
            stack.enter_context(patch.object(sr, "build_work", return_value=works))
            stack.enter_context(patch.object(sr, "file_identity", return_value={"sha256": "b" * 64}))
            stack.enter_context(patch.object(sr, "climate_change_identity", return_value={"usn": 1}))
            stack.enter_context(patch.object(sr, "require_unchanged_climate", side_effect=climate_guard))
            stack.enter_context(patch.object(sr, "open_store", return_value=group))
            stack.enter_context(patch.object(sr, "array_specs", return_value={"field": ((2, 2), "f4", 0)}))
            stack.enter_context(patch.object(sr, "site_result", side_effect=compute))
            stack.enter_context(patch.object(sr, "atomic_json", side_effect=atomic))
            stack.enter_context(patch.object(sr, "install_private_site", side_effect=install))
            stack.enter_context(patch.object(sr, "build_database", return_value=output / "fixture.sqlite"))
            stack.enter_context(patch.object(sr, "write_reports"))
            receipt = stack.enter_context(patch.object(sr, "save_receipt"))
            yield group, events, receipt

    def test_run_commits_zarr_checkpoint_and_completion_on_caller_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.fixture(output) as (group, events, receipt):
                result = sr.run(output, "FT0", workers=3, memory_budget_mb=1536, reuse=False)
            self.assertEqual(result["generated"], 3)
            self.assertEqual(result["site_worker_limit"], 3)
            expected = []
            for index in range(3):
                expected.extend([("complete", index, 0), ("install", index, None),
                                 ("field", index, None), ("checkpoint", index, None),
                                 ("complete", index, 1)])
            self.assertEqual(events, expected)
            np.testing.assert_array_equal(group["site_complete"].values, [1, 1, 1])
            receipt.assert_called_once()
            self.assertFalse(list(output.glob(".physical-*")))

    def test_public_write_failure_never_marks_site_or_final_receipt_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.fixture(output, fail_write=True) as (group, events, receipt):
                with self.assertRaisesRegex(OSError, "public write failure"):
                    sr.run(output, "FT0", workers=2, reuse=False)
            self.assertEqual(int(group["site_complete"].values[0]), 0)
            self.assertFalse(list((output / "checkpoints").glob("*.json")))
            receipt.assert_not_called()
            self.assertFalse(list(output.glob(".physical-*")))

    def test_changed_source_blocks_all_public_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.fixture(output, source_changed=True) as (group, events, receipt):
                with self.assertRaisesRegex(RuntimeError, "Climate archive changed"):
                    sr.run(output, "FT0", workers=2, reuse=False)
            self.assertEqual(events, [])
            receipt.assert_not_called()
            self.assertFalse(list(output.glob(".physical-*")))


if __name__ == "__main__":
    unittest.main()
