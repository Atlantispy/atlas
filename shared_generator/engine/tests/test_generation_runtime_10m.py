"""Small-array orchestration tests; no production sources are read or generated."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from collections import defaultdict
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import shapely

import build_stage6c5_10m as s5
import build_stage6c5r_physical_10m as sr


def candidate(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        index=index, semantic_key=f"{index:064x}",
        tile_parent_row0=4 + index, tile_parent_col0=5 + index,
        site=SimpleNamespace(settlement_id=f"SITE-{index}"),
    )


def group_for(count: int) -> dict[str, np.ndarray]:
    return {"elevation_m": np.zeros((count, 100, 100), dtype=np.float32),
            "site_complete": np.zeros(count, dtype=np.uint8)}


def simple_specs() -> dict[str, tuple[str, float]]:
    return {"elevation_m": ("f4", float("nan"))}


class FakeRasters:
    def __init__(self, authority: dict):
        self.owner = threading.get_ident()
        self.closed = False
        self.terrain = SimpleNamespace(descriptor=authority, read_block=self.terrain_read)

    def terrain_read(self, row: int, col: int, height: int, width: int) -> np.ndarray:
        if threading.get_ident() != self.owner:
            raise AssertionError("Live source handle escaped the coordinator")
        return np.add.outer(np.arange(row, row + height) * 1000,
                            np.arange(col, col + width)).astype(np.float32)

    def read_block(self, *window) -> dict[str, np.ndarray]:
        terrain = self.terrain_read(*window)
        return {"terrain": terrain, "slope": np.hypot(*np.gradient(terrain))}

    def close(self) -> None:
        self.closed = True


@contextmanager
def run_fixtures(items, group):
    with ExitStack() as stack:
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = ("ok",)
        sql = stack.enter_context(patch.object(s5, "sqlite_readonly"))
        sql.return_value.__enter__.return_value = connection
        stack.enter_context(patch.object(s5.s6c, "verify_sources", return_value=([], {
            "authority_id": "terrain", "generation": 3, "root_hash": "a" * 64,
        }, {})))
        stack.enter_context(patch.object(s5, "load_candidates", return_value=items))
        stack.enter_context(patch.object(s5, "open_evidence_store", return_value=group))
        stack.enter_context(patch.object(s5, "file_identity", return_value={"sha256": "b" * 64, "size_bytes": 1}))
        stack.enter_context(patch.object(s5, "runtime_implementation", return_value={"code": "fixture-v1"}))
        stack.enter_context(patch.object(s5, "capture_source_guards", return_value={}))
        stack.enter_context(patch.object(s5, "require_terrain_identity"))
        stack.enter_context(patch.object(s5, "zarr_arrays", side_effect=simple_specs))
        yield stack


class PreparedRasterTests(unittest.TestCase):
    def test_original_site_result_matches_preloaded_split_numerically(self):
        original_path = Path(s5.__file__).resolve().parents[2] / "original" / "engine" / "build_stage6c5_10m.py"
        if not original_path.is_file():
            original_path = (Path(s5.__file__).resolve().parents[1] / "runtime_work" /
                             "engineering_installations" / "GEO-ENG-RUNTIME-2026-09-02-01" /
                             "predecessor" / "engine" / "build_stage6c5_10m.py")
        if not original_path.is_file():
            self.skipTest("Retained predecessor oracle is unavailable in this checkout")
        tree = ast.parse(original_path.read_text(encoding="utf-8-sig"))
        original_function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "site_result")
        policy, _ = s5.rules._resolved_policy("AGRARIAN_SETTLEMENT", "SURFACE", "FIXTURE")
        profile = {"realised_settlement_form": "AGRARIAN_SETTLEMENT", "effective_vertical_domain": "SURFACE",
                   "haus_id": "FIXTURE", "access_operator": policy["access_operator"],
                   **{f"band_t{index + 1}": value for index, value in enumerate(policy["band_thresholds"])}}
        site = s5.s6c.Site("FIXTURE", 3.05, 3.05, 1, 1, 1, 0, None,
                           "FT0_HAUS_PRINCIPAL_SITE", "AGRARIAN_SETTLEMENT", "SURFACE", "SURFACE", 1)
        inherited = defaultdict(lambda: 0.5, {
            "limiting_factors_json": "[]", "analysis_status": "READY_2D_CURRENT",
            "capacity_band": "CB2_MODERATE", "provisional_anchor": 0,
            "horizontal_uncertainty_radius_km": 0.2,
        })
        item = s5.Candidate(1, site, inherited, profile, "COMPLETE_2D_REFINEMENT",
                            26, 26, 20, 20, "FIXTURE-TILE", "d" * 64)
        topology = SimpleNamespace(carrier_baronies=np.ones((5, 5), dtype=np.int32),
                                   partial_carriers_by_row={})
        vectors = object.__new__(s5.s6c.VectorStack)
        line = shapely.LineString([(2.0, 2.0), (4.2, 4.2)])
        for name in ("active_index_tree", "perennial_index_tree", "major_index_tree", "minor_tree",
                     "special_tree", "permanent_lake_tree", "seasonal_lake_tree", "coast_index_tree"):
            setattr(vectors, name, shapely.STRtree([line]))
        vectors.coast_cover_polygons = []

        class SmoothRasters(FakeRasters):
            def terrain_read(self, row, col, height, width):
                rr, cc = np.meshgrid(np.arange(row, row + height), np.arange(col, col + width), indexing="ij")
                return (100.0 + rr * 0.1 + cc * 0.05 + np.sin(rr * 0.2) * 0.01).astype(np.float32)

            def read_block(self, *window):
                values = self.terrain_read(*window)
                masks = np.zeros(values.shape, dtype=np.uint8)
                return {"terrain": values, "sea": masks.copy(), "wetland": masks.copy(),
                        "seren": masks.copy(), "flood_exposure": masks.astype(np.float32)}

        rasters = SmoothRasters({"root_hash": "e" * 64})
        group = {name: np.full((2, 100, 100), fill, dtype=dtype)
                 for name, (dtype, fill) in s5.zarr_arrays().items()}
        group["site_complete"] = np.zeros(2, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(s5, "write_tile_recovery_bundle") as write_bundle, \
                patch.object(s5, "verified_bundle_manifest", return_value={"bundle_id": "fixture", "packet_count": 1}):
            namespace = dict(vars(s5))
            exec(compile(ast.Module(body=[original_function], type_ignores=[]), str(original_path), "exec"), namespace)
            old = namespace["site_result"](item, rasters, topology, vectors, Path(directory) / "old", group)
            old_tile = write_bundle.call_args.args[0]
            prepared = s5.prepare_candidate_rasters(item, rasters)
            new, arrays = s5.compute_site_result(item, prepared, topology, vectors, Path(directory) / "new")
            new_tile = write_bundle.call_args.args[0]
            for name in s5.zarr_arrays():
                np.testing.assert_array_equal(group[name][item.index], arrays[name], err_msg=name)
            for name in old_tile.encoded_arrays:
                np.testing.assert_array_equal(old_tile.encoded_arrays[name], new_tile.encoded_arrays[name], err_msg=name)
            old.pop("completed_utc")
            new.pop("completed_utc")
            self.assertEqual(old, new)

    def test_preloaded_arrays_match_live_windows_and_are_independent(self):
        item = candidate(0)
        live = FakeRasters({"root_hash": "terrain"})
        prepared = s5.prepare_candidate_rasters(item, live)
        window = (item.tile_parent_row0, item.tile_parent_col0, 22, 22)
        np.testing.assert_array_equal(prepared.terrain.read_block(*window), live.terrain_read(*window))
        for key, value in live.read_block(*window).items():
            np.testing.assert_array_equal(prepared.read_block(*window)[key], value)
        changed = prepared.read_block(*window)
        changed["terrain"][:] = -999
        self.assertFalse(np.any(prepared.core["terrain"] == -999))
        with self.assertRaises(ValueError):
            prepared.terrain.read_block(0, 0, 1, 1)
        with self.assertRaises(ValueError):
            prepared.read_block(0, 0, 22, 22)

    def test_completion_marker_can_wait_for_checkpoint_commit(self):
        group = group_for(1)
        group["site_complete"][0] = 1
        arrays = {"elevation_m": np.ones((100, 100), dtype=np.float32)}
        with patch.object(s5, "zarr_arrays", side_effect=simple_specs):
            s5.write_evidence_slice(group, 0, arrays, mark_complete=False)
        self.assertEqual(int(group["site_complete"][0]), 0)
        np.testing.assert_array_equal(group["elevation_m"][0], arrays["elevation_m"])

    def test_array_write_failure_leaves_incomplete_marker(self):
        group = group_for(1)
        group["site_complete"][0] = 1
        with patch.object(s5, "zarr_arrays", side_effect=simple_specs):
            with self.assertRaises(ValueError):
                s5.write_evidence_slice(group, 0, {"elevation_m": np.zeros((2, 2))})
        self.assertEqual(int(group["site_complete"][0]), 0)


class CheckpointTests(unittest.TestCase):
    def test_runtime_change_invalidates_even_matching_arrays(self):
        item = candidate(0)
        group = group_for(1)
        group["site_complete"][0] = 1
        with tempfile.TemporaryDirectory() as directory, patch.object(s5, "zarr_arrays", side_effect=simple_specs):
            root = Path(directory)
            checkpoint = {"semantic_key": item.semantic_key, "runtime_identity": "old",
                          "evidence_digest": s5.evidence_slice_digest({"elevation_m": group["elevation_m"][0]}),
                          "bundle_relative_path": "tile_cache/a", "bundle_id": "bundle"}
            s5.atomic_json(root / "checkpoint.json", checkpoint)
            with patch.object(s5, "verified_bundle_manifest", return_value={"bundle_id": "bundle"}) as verify:
                self.assertIsNone(s5.load_checkpoint(root / "checkpoint.json", item, group, root, runtime_identity="new"))
                verify.assert_not_called()
                self.assertIsNotNone(s5.load_checkpoint(root / "checkpoint.json", item, group, root, runtime_identity="old"))
                group["elevation_m"][0, 0, 0] = 9
                self.assertIsNone(s5.load_checkpoint(root / "checkpoint.json", item, group, root, runtime_identity="old"))

    def test_no_reuse_does_not_read_old_checkpoints(self):
        loader = MagicMock(side_effect=AssertionError("unexpected read"))
        self.assertEqual(s5.checkpoint_plan([1, 2], loader, reuse=False), [None, None])

    def test_bundle_install_retains_predecessor_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private"
            source = private / "tile_cache" / "a.bundle"
            target = root / "output" / "tile_cache" / "a.bundle"
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (source / "marker").write_text("new")
            (target / "marker").write_text("old")
            with patch.object(s5, "verified_bundle_manifest", return_value={"bundle_id": "id"}):
                s5.install_private_bundle(root / "output", private, {
                    "bundle_relative_path": "tile_cache/a.bundle", "bundle_id": "id",
                })
                self.assertEqual((target / "marker").read_text(), "new")
                previous = list((root / "output" / "predecessor_bundles").glob("*/a.bundle/marker"))
                self.assertEqual(len(previous), 1)
                self.assertEqual(previous[0].read_text(), "old")
                with self.assertRaises(ValueError):
                    s5.install_private_bundle(root / "output", private, {
                        "bundle_relative_path": "../../escape", "bundle_id": "id",
                    })

    def test_bundle_install_rolls_back_predecessor_on_move_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, output = root / "private", root / "output"
            source, target = private / "tile_cache/a", output / "tile_cache/a"
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (target / "marker").write_text("old")
            replace = s5.os.replace

            def failing_replace(src, dst):
                if Path(src) == source:
                    raise OSError("fixture move failed")
                return replace(src, dst)

            with patch.object(s5, "verified_bundle_manifest", return_value={"bundle_id": "id"}), \
                    patch.object(s5.os, "replace", side_effect=failing_replace):
                with self.assertRaisesRegex(OSError, "fixture move failed"):
                    s5.install_private_bundle(output, private, {"bundle_relative_path": "tile_cache/a", "bundle_id": "id"})
            self.assertEqual((target / "marker").read_text(), "old")

    def test_sqlite_wal_and_source_change_guards_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.sqlite"
            path.write_bytes(b"fixture")
            with patch.object(s5, "windows_file_change_token", return_value=None):
                guards = s5.capture_source_guards([path])
                s5.require_source_guards(guards)
                path.write_bytes(b"changed fixture")
                with self.assertRaisesRegex(RuntimeError, "changed during"):
                    s5.require_source_guards(guards)
                path.with_name(path.name + "-wal").write_bytes(b"uncheckpointed")
                with self.assertRaisesRegex(RuntimeError, "SQLite source"):
                    s5.capture_source_guards([path])


class RunTests(unittest.TestCase):
    def test_fully_reused_skips_heavy_inputs_and_final_writes(self):
        items = [candidate(0)]
        with tempfile.TemporaryDirectory() as directory, run_fixtures(items, group_for(1)) as stack:
            stack.enter_context(patch.object(s5, "load_checkpoint", return_value={"semantic_key": items[0].semantic_key}))
            stack.enter_context(patch.object(s5, "load_receipt", return_value={"status": "BUILD_COMPLETE"}))
            topology = stack.enter_context(patch.object(s5.s6c, "ExactSurfaceIndex", side_effect=AssertionError("eager topology")))
            stack.enter_context(patch.object(s5.s6c, "VectorStack", side_effect=AssertionError("eager vectors")))
            stack.enter_context(patch.object(s5.s6c, "RasterStack", side_effect=AssertionError("eager rasters")))
            build = stack.enter_context(patch.object(s5, "build_database"))
            docs = stack.enter_context(patch.object(s5, "write_documentation"))
            result = s5.run(Path(directory))
            self.assertTrue(result["final_outputs_reused"])
            self.assertEqual(result["generated"], 0)
            self.assertEqual(result["reused"], 1)
            topology.assert_not_called()
            build.assert_not_called()
            docs.assert_not_called()

    def test_missing_receipt_rebuilds_final_outputs_not_sites(self):
        items = [candidate(0)]
        with tempfile.TemporaryDirectory() as directory, run_fixtures(items, group_for(1)) as stack:
            root = Path(directory)
            stack.enter_context(patch.object(s5, "load_checkpoint", return_value={"semantic_key": items[0].semantic_key}))
            stack.enter_context(patch.object(s5, "load_receipt", return_value=None))
            stack.enter_context(patch.object(s5.s6c, "ExactSurfaceIndex", side_effect=AssertionError("eager topology")))
            build = stack.enter_context(patch.object(s5, "build_database", return_value=(root / "a.sqlite", root / "b.gpkg")))
            docs = stack.enter_context(patch.object(s5, "write_documentation"))
            save = stack.enter_context(patch.object(s5, "save_receipt"))
            result = s5.run(root)
            self.assertEqual(result["generated"], 0)
            self.assertFalse(result["final_outputs_reused"])
            build.assert_called_once()
            docs.assert_called_once()
            save.assert_called_once()

    def test_serial_parallel_array_equivalence_and_coordinator_commits(self):
        snapshots = []
        worker_threads = set()
        coordinator = threading.get_ident()
        for workers in (1, 2):
            items = [candidate(index) for index in range(3)]
            group = group_for(3)
            with tempfile.TemporaryDirectory() as directory, run_fixtures(items, group) as stack:
                stack.enter_context(patch.object(s5.s6c, "ExactSurfaceIndex", return_value=object()))
                stack.enter_context(patch.object(s5.s6c, "VectorStack", return_value=object()))
                stack.enter_context(patch.object(s5.s6c, "RasterStack", side_effect=FakeRasters))
                stack.enter_context(patch.object(s5, "load_checkpoint", side_effect=AssertionError("no-reuse read")))

                def compute(item, prepared, topology, vectors, private_dir):
                    worker_threads.add(threading.get_ident())
                    # Real deterministic ndarray maths, with deliberately different job durations.
                    support = prepared.terrain.values
                    value = np.mean(np.hypot(*np.gradient(support)), dtype=np.float64)
                    arrays = {"elevation_m": np.full((100, 100), value + item.index, dtype=np.float32)}
                    bundle = private_dir / "tile_cache" / f"{item.index}.zstbundle"
                    bundle.mkdir()
                    (bundle / "manifest.json").write_text(json.dumps({"bundle_id": str(item.index)}))
                    time.sleep(0.005 * (3 - item.index))
                    return {"bundle_relative_path": bundle.relative_to(private_dir).as_posix(),
                            "bundle_id": str(item.index), "semantic_key": item.semantic_key,
                            "evidence_digest": s5.evidence_slice_digest(arrays)}, arrays

                stack.enter_context(patch.object(s5, "compute_site_result", side_effect=compute))
                stack.enter_context(patch.object(s5, "verified_bundle_manifest", side_effect=lambda path: json.loads((path / "manifest.json").read_text())))
                original_write = s5.write_evidence_slice
                commit_order = []

                def write(group, index, arrays, **kwargs):
                    self.assertEqual(threading.get_ident(), coordinator)
                    commit_order.append(index)
                    return original_write(group, index, arrays, **kwargs)

                stack.enter_context(patch.object(s5, "write_evidence_slice", side_effect=write))
                result = s5.run(Path(directory), limit=3, workers=workers, reuse=False)
                self.assertEqual(result["generated"], 3)
                self.assertEqual(commit_order, [0, 1, 2])
                self.assertTrue(np.all(group["site_complete"] == 1))
                for item in items:
                    checkpoint = s5.read_json(Path(directory) / "checkpoints" / f"{item.site.settlement_id}.json")
                    self.assertIn("runtime_identity", checkpoint)
                snapshots.append(group["elevation_m"].copy())
        np.testing.assert_array_equal(snapshots[0], snapshots[1])
        self.assertGreater(len(worker_threads), 1)

    def test_worker_failure_does_not_commit_later_sites(self):
        items = [candidate(index) for index in range(3)]
        group = group_for(3)
        with tempfile.TemporaryDirectory() as directory, run_fixtures(items, group) as stack:
            root = Path(directory)
            stack.enter_context(patch.object(s5.s6c, "ExactSurfaceIndex", return_value=object()))
            stack.enter_context(patch.object(s5.s6c, "VectorStack", return_value=object()))
            stack.enter_context(patch.object(s5.s6c, "RasterStack", side_effect=FakeRasters))

            def compute(item, prepared, topology, vectors, private_dir):
                if item.index == 1:
                    raise RuntimeError("fixture worker failed")
                arrays = {"elevation_m": np.ones((100, 100), dtype=np.float32) * item.index}
                bundle = private_dir / "tile_cache" / f"{item.index}.zstbundle"
                bundle.mkdir()
                (bundle / "manifest.json").write_text(json.dumps({"bundle_id": str(item.index)}))
                return {"bundle_relative_path": bundle.relative_to(private_dir).as_posix(),
                        "bundle_id": str(item.index), "semantic_key": item.semantic_key,
                        "evidence_digest": s5.evidence_slice_digest(arrays)}, arrays

            stack.enter_context(patch.object(s5, "compute_site_result", side_effect=compute))
            stack.enter_context(patch.object(s5, "verified_bundle_manifest", side_effect=lambda path: json.loads((path / "manifest.json").read_text())))
            with self.assertRaisesRegex(RuntimeError, "fixture worker failed"):
                s5.run(root, limit=3, workers=2, reuse=False)
            self.assertEqual(group["site_complete"].tolist(), [1, 0, 0])
            self.assertTrue((root / "checkpoints" / "SITE-0.json").is_file())
            self.assertFalse((root / "checkpoints" / "SITE-2.json").exists())
            self.assertEqual(list(root.glob(".s6c5-private-*")), [])


class PhysicalResumeTests(unittest.TestCase):
    def test_fully_reused_physical_run_skips_climate_and_heavy_stacks(self):
        items = [candidate(0)]
        work = SimpleNamespace(candidate=items[0])
        with tempfile.TemporaryDirectory() as directory, run_fixtures(items, group_for(1)) as stack:
            stack.enter_context(patch.object(sr, "EXPECTED_ALL", 1))
            stack.enter_context(patch.object(sr, "scope_candidates", return_value=items))
            stack.enter_context(patch.object(sr, "build_work", return_value=[work]))
            stack.enter_context(patch.object(sr, "source_identity", return_value={"frozen": "fixture"}))
            stack.enter_context(patch.object(sr, "file_identity", return_value={"sha256": "b" * 64, "size_bytes": 1}))
            stack.enter_context(patch.object(sr, "climate_change_identity", return_value={"usn": 7}))
            stack.enter_context(patch.object(sr, "open_store", return_value={}))
            stack.enter_context(patch.object(sr, "load_checkpoint", return_value={"semantic_key": "fixture"}))
            stack.enter_context(patch.object(sr, "load_receipt", return_value={"status": "BUILD_COMPLETE_REVIEW_ONLY"}))
            stack.enter_context(patch.object(sr.s6c, "ExactSurfaceIndex", side_effect=AssertionError("eager topology")))
            stack.enter_context(patch.object(sr, "C1MonthlyClimateReader", side_effect=AssertionError("eager climate")))
            build = stack.enter_context(patch.object(sr, "build_database"))
            reports = stack.enter_context(patch.object(sr, "write_reports"))
            result = sr.run(Path(directory), "FT0")
            self.assertTrue(result["final_outputs_reused"])
            build.assert_not_called()
            reports.assert_not_called()

    def test_changed_climate_token_fails_closed(self):
        with patch.object(sr, "climate_change_identity", return_value={"usn": 8}):
            with self.assertRaisesRegex(RuntimeError, "Climate archive changed"):
                sr.require_unchanged_climate({"usn": 7})

    def test_missing_strong_climate_token_disables_checkpoint_reuse(self):
        items = [candidate(0)]
        work = SimpleNamespace(candidate=items[0])
        with tempfile.TemporaryDirectory() as directory, run_fixtures(items, group_for(1)) as stack:
            stack.enter_context(patch.object(sr, "EXPECTED_ALL", 1))
            stack.enter_context(patch.object(sr, "scope_candidates", return_value=items))
            stack.enter_context(patch.object(sr, "build_work", return_value=[work]))
            stack.enter_context(patch.object(sr, "source_identity", return_value={}))
            stack.enter_context(patch.object(sr, "file_identity", return_value={"sha256": "b" * 64, "size_bytes": 1}))
            stack.enter_context(patch.object(sr, "climate_change_identity", return_value=None))
            stack.enter_context(patch.object(sr, "open_store", return_value={}))
            load = stack.enter_context(patch.object(sr, "load_checkpoint"))
            stack.enter_context(patch.object(sr.s6c, "ExactSurfaceIndex", side_effect=RuntimeError("generation required")))
            with self.assertRaisesRegex(RuntimeError, "generation required"):
                sr.run(Path(directory), "FT0")
            load.assert_not_called()

    def test_physical_invalid_worker_count_is_rejected(self):
        with self.assertRaises(ValueError):
            sr.run(Path("unused"), "FT0", workers=0)


if __name__ == "__main__":
    unittest.main()
