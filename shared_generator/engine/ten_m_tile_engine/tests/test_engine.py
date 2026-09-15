from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np

PACKAGE_PARENT = next(
    directory
    for directory in Path(__file__).resolve().parents
    if (directory / "ten_m_tile_engine").is_dir()
)
DEPENDENCIES = PACKAGE_PARENT / "generator_deps"
for candidate in (str(DEPENDENCIES), str(PACKAGE_PARENT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from ten_m_tile_engine import (  # noqa: E402
    CategoricalRecipe,
    ContinuousRecipe,
    GridSpec,
    ParentRasterWindow,
    PolygonFeature,
    TerrainRecipe,
    TileSpec,
    decode_compact_tile,
    refine_continuous,
    refine_parent_probabilities,
    refine_terrain,
    rasterize_exact_vectors,
)
from ten_m_tile_engine.cache import (  # noqa: E402
    ActivityMode,
    ActivityPolicyController,
    CacheCorruptionError,
    ContentAddressedCache,
    PacketBatch,
    ingest_recovery_bundle,
    ingest_segment,
    read_recovery_manifest,
    read_legacy_zip_entries,
    read_segment_header,
    write_tile_recovery_bundle,
)


SOURCES = {"synthetic_parent": "a" * 64}


def synthetic_parent() -> ParentRasterWindow:
    rows, cols = np.mgrid[0:10, 0:12]
    data = 800.0 - 3.0 * rows + 2.0 * cols + 0.15 * rows * cols + 0.05 * cols**2
    return ParentRasterWindow(data.astype(np.float64), 0, 0, GridSpec(1000.0, 9000.0))


def overlap(array_a, spec_a, array_b, spec_b, global_rows, global_cols):
    ar = global_rows - spec_a.fine_row0
    ac = global_cols - spec_a.fine_col0
    br = global_rows - spec_b.fine_row0
    bc = global_cols - spec_b.fine_col0
    return array_a[np.ix_(ar, ac)], array_b[np.ix_(br, bc)]


class GridAndTerrainTests(unittest.TestCase):
    def test_exact_nesting_and_metadata_contract(self):
        grid = GridSpec(1000.0, 9000.0)
        spec = TileSpec("nest", 3, 5, 2, 3, halo_cells=7)
        self.assertEqual(spec.fine_row0, 23)
        self.assertEqual(spec.fine_col0, 43)
        self.assertEqual(spec.fine_height, 34)
        child_rows = 3 * 10 + np.arange(10)
        child_cols = 5 * 10 + np.arange(10)
        rr, cc = np.meshgrid(child_rows, child_cols, indexing="ij")
        x, y = grid.fine_center(rr, cc)
        self.assertAlmostEqual(float(x.mean()), grid.origin_x_m + 5.5 * 100.0)
        self.assertAlmostEqual(float(y.mean()), grid.origin_y_m + 3.5 * 100.0)
        self.assertEqual(grid.fine_transform(0, 0)[4], 10.0)
        self.assertEqual(grid.crs, "LOCAL_CARTESIAN_M_NO_EPSG")

    def test_terrain_parent_recovery_gradients_and_compact_decode(self):
        parent = synthetic_parent()
        spec = TileSpec("terrain", 2, 2, 4, 5, halo_cells=12)
        recipe = TerrainRecipe(
            effective_resolution_m=100.0,
            elevation_scale_m=0.01,
            max_micro_relief_m=0.15,
            micro_relief_slope_fraction=0.15,
        )
        tile = refine_terrain(parent, spec, recipe, SOURCES)
        required = {
            "elevation_10m",
            "broad_elevation_10m",
            "broad_gradient_x_10m",
            "broad_gradient_y_10m",
            "broad_gradient_magnitude_10m",
            "broad_downslope_aspect_deg_10m",
            "local_gradient_x_10m",
            "local_gradient_y_10m",
            "local_gradient_magnitude_10m",
            "local_downslope_aspect_deg_10m",
        }
        self.assertTrue(required.issubset(tile.arrays))
        self.assertLess(tile.metadata["qa"]["parent_aggregation_max_abs_error_m"], 1e-4)
        self.assertLess(tile.metadata["qa"]["broad_parent_aggregation_max_abs_error_m"], 1e-8)
        self.assertGreater(tile.metadata["qa"]["broad_gradient_direction_min_cosine"], 0.8)
        self.assertGreater(tile.metadata["qa"]["local_gradient_direction_min_cosine"], 0.6)
        self.assertEqual(tile.metadata["resolution_status"], "MODELLED_10M")
        self.assertEqual(tile.metadata["review_status"], "DERIVED_REVIEW_ONLY")
        self.assertEqual(tile.metadata["cell_size_m"], 10.0)
        self.assertEqual(tile.metadata["model_resolution_m"], 10.0)
        self.assertEqual(tile.metadata["physical_source_resolution_m"], 100.0)
        self.assertEqual(tile.metadata["effective_evidence_resolution_m"], 100.0)
        self.assertEqual(tile.metadata["effective_resolution_m"], 100.0)
        self.assertEqual(tile.metadata["source_hashes"], SOURCES)
        self.assertEqual(len(tile.metadata["recipe_hash"]), 64)
        with tempfile.TemporaryDirectory() as temporary:
            array_path, meta_path = tile.save(temporary, compact=True)
            with np.load(array_path, allow_pickle=False) as archive:
                stored = {name: archive[name] for name in archive.files}
            decoded = decode_compact_tile(stored, json.loads(meta_path.read_text("utf-8")))
            np.testing.assert_allclose(decoded["elevation_10m"], tile.arrays["elevation_10m"], atol=1e-6)
            self.assertNotIn("elevation_10m", stored)

    def test_adjacent_tiles_are_seam_consistent(self):
        parent = synthetic_parent()
        recipe = TerrainRecipe(100.0, max_micro_relief_m=0.1)
        left_spec = TileSpec("left", 2, 2, 4, 2, halo_cells=12)
        right_spec = TileSpec("right", 2, 4, 4, 2, halo_cells=12)
        left = refine_terrain(parent, left_spec, recipe, SOURCES)
        right = refine_terrain(parent, right_spec, recipe, SOURCES)
        # Four columns around the shared core edge and the full common core rows;
        # these are well inside both halos, so all finite-difference bands agree.
        rows = np.arange(20, 60)
        cols = np.arange(38, 42)
        for name in (
            "elevation_10m",
            "broad_elevation_10m",
            "broad_gradient_x_10m",
            "broad_gradient_y_10m",
            "local_gradient_x_10m",
            "local_gradient_y_10m",
        ):
            a, b = overlap(left.arrays[name], left_spec, right.arrays[name], right_spec, rows, cols)
            np.testing.assert_array_equal(a, b, err_msg=name)

    def test_generic_continuous_is_parent_conserving(self):
        parent = synthetic_parent()
        spec = TileSpec("continuous", 2, 3, 2, 2, halo_cells=5)

        def evidence(pr, pc, x, y, parent_value):
            return parent_value + 0.8 * np.sin(x / 37.0) + 0.3 * np.cos(y / 43.0)

        tile = refine_continuous(
            parent,
            spec,
            ContinuousRecipe("rainfall", 0.001, 100.0),
            SOURCES,
            evidence,
        )
        self.assertLess(tile.metadata["qa"]["parent_aggregation_max_abs_error"], 1e-5)


class CategoricalTests(unittest.TestCase):
    def test_probability_projection_preserves_parent(self):
        grid = GridSpec(0.0, 1000.0)
        probabilities = np.empty((3, 3, 3), dtype=np.float64)
        probabilities[0] = 0.2
        probabilities[1] = 0.3
        probabilities[2] = 0.5
        spec = TileSpec("probability", 0, 0, 3, 3, halo_cells=0)

        def evidence(pr, pc, x, y, target):
            raw = np.broadcast_to(target[:, None, None], (3, 10, 10)).copy()
            raw[0] *= 1.0 + 0.6 * np.sin(x / 25.0)
            raw[1] *= 1.0 + 0.5 * np.cos(y / 29.0)
            raw[2] *= 1.0 + 0.3 * np.sin((x + y) / 41.0)
            return np.maximum(raw, 1e-6)

        tile = refine_parent_probabilities(
            probabilities,
            0,
            0,
            grid,
            spec,
            CategoricalRecipe("biome", 100.0),
            SOURCES,
            evidence,
        )
        self.assertLess(tile.metadata["qa"]["parent_probability_max_abs_error"], 2e-7)
        self.assertLess(tile.metadata["qa"]["pixel_simplex_max_abs_error"], 2e-6)

    def test_exact_vector_rasterization_is_deterministic(self):
        grid = GridSpec(0.0, 1000.0)
        spec = TileSpec("vector", 0, 0, 2, 2, halo_cells=0)
        feature = PolygonFeature(
            "forest-a",
            7,
            ((20.0, 1020.0), (180.0, 1020.0), (180.0, 1180.0), (20.0, 1180.0)),
        )
        recipe = CategoricalRecipe("biome_class", 10.0)
        first = rasterize_exact_vectors(grid, spec, [feature], recipe, SOURCES)
        second = rasterize_exact_vectors(grid, spec, [feature], recipe, SOURCES)
        np.testing.assert_array_equal(first.arrays["biome_class"], second.arrays["biome_class"])
        self.assertEqual(np.count_nonzero(first.arrays["biome_class"] == 7), 16 * 16)


class CacheAndTransportTests(unittest.TestCase):
    def test_atomic_cache_write_survives_long_workspace_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            segment = "bounded-generator-cache-path"
            while len(str(root / "objects" / "00" / (("0" * 64) + ".zst"))) < 230:
                root /= segment
            cache = ContentAddressedCache(root)
            raw = b"fresh-long-path-cache-object" * 100
            content_hash = cache.put(raw)
            self.assertEqual(cache.get(content_hash), raw)

    def test_legacy_zip_is_readable_but_not_release_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            legacy = Path(temporary) / "legacy.zip"
            with zipfile.ZipFile(legacy, "w") as archive:
                archive.writestr("old/source.txt", b"legacy-readable")
            self.assertEqual(read_legacy_zip_entries(legacy)["old/source.txt"], b"legacy-readable")

    def test_authoritative_recovery_bundle_uses_independent_zstd_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = b"base-terrain" * 500
            target = bytearray(base)
            target[20:28] = b"10M-TILE"
            target = bytes(target)
            final = b"independent-final" * 400
            batch = PacketBatch()
            batch.add_full(base, {"kind": "terrain"}, "base.bin")
            batch.add_patch(base, target, {"kind": "terrain"}, "target.bin")
            batch.add_full(final, {"kind": "terrain"}, "final.bin")
            bundle = batch.flush_recovery_bundle(root / "release.zstbundle")
            manifest = read_recovery_manifest(bundle)
            self.assertTrue(manifest["authoritative_master"])
            self.assertFalse(manifest["legacy_zip_default"])
            frame_paths = [item["frame_path"] for item in manifest["packets"]]
            self.assertTrue(all(path.endswith(".zst") for path in frame_paths))
            cache = ContentAddressedCache(root / "clean-cache")
            report = ingest_recovery_bundle(bundle, cache)
            self.assertEqual(report.applied_sequences, [0, 1, 2])
            self.assertFalse(report.failed_sequences)
            # Damage only the PATCH frame: FULL frames before and after recover.
            damaged_frame = bundle / manifest["packets"][1]["frame_path"]
            damaged = bytearray(damaged_frame.read_bytes())
            damaged[len(damaged) // 2] ^= 0x7C
            damaged_frame.write_bytes(damaged)
            recovery_cache = ContentAddressedCache(root / "partial-recovery-cache")
            partial = ingest_recovery_bundle(bundle, recovery_cache)
            self.assertEqual(partial.applied_sequences, [0, 2])
            self.assertIn(1, partial.failed_sequences)

    def test_tile_delivery_defaults_to_manifest_indexed_zstd_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = synthetic_parent()
            tile = refine_terrain(
                parent,
                TileSpec("delivery", 2, 2, 1, 1, halo_cells=2),
                TerrainRecipe(100.0),
                SOURCES,
            )
            bundle = write_tile_recovery_bundle(tile, Path(temporary) / "tile.zstbundle")
            manifest = read_recovery_manifest(bundle)
            paths = [item["artifact_path"] for item in manifest["packets"]]
            self.assertIn("delivery/metadata.json", paths)
            self.assertTrue(any(path.endswith("elevation_residual_q.npy") for path in paths))
            self.assertTrue(all(item["kind"] == "full" for item in manifest["packets"]))

    def test_full_ref_patch_and_persistent_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = ContentAddressedCache(root / "cache")
            base = bytes(range(256)) * 8
            target = bytearray(base)
            target[17:25] = b"DIADEM10"
            target = bytes(target)
            other = b"other-tile" * 300
            base_hash = cache.put(base, pinned=True)
            batch = PacketBatch()
            template = {"bands": ["elevation", "slope"], "cell_size_m": 10}
            batch.add_ref(base_hash, template)
            target_hash = batch.add_patch(base, target, template)
            other_hash = batch.add_full(other, template)
            segment = batch.flush(root / "ordered.segment")
            header, _ = read_segment_header(segment)
            self.assertEqual(len(header["templates"]), 1)
            self.assertEqual([item["kind"] for item in header["packets"]], ["ref", "patch", "full"])
            report = ingest_segment(segment, cache)
            self.assertEqual(report.applied_sequences, [0, 1, 2])
            self.assertFalse(report.failed_sequences)
            self.assertEqual(cache.get(target_hash), target)
            self.assertEqual(cache.get(other_hash), other)
            # A fresh process-equivalent cache instance reuses prior chunks.
            reopened = ContentAddressedCache(root / "cache")
            self.assertEqual(reopened.get(target_hash), target)
            self.assertTrue(reopened.has(base_hash, verify=True))

    def test_corrupt_middle_zstd_frame_does_not_hide_later_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = PacketBatch()
            hashes = [batch.add_full((f"tile-{index}-".encode() * 500)) for index in range(3)]
            segment = batch.flush(root / "clean.segment")
            header, payload_start = read_segment_header(segment)
            damaged = bytearray(segment.read_bytes())
            middle = header["packets"][1]
            position = payload_start + middle["frame_offset"] + middle["frame_size"] // 2
            damaged[position] ^= 0x5A
            corrupt_segment = root / "one-frame-damaged.segment"
            corrupt_segment.write_bytes(damaged)
            cache = ContentAddressedCache(root / "recovery-cache")
            report = ingest_segment(corrupt_segment, cache, recover_independent_frames=True)
            self.assertEqual(report.applied_sequences, [0, 2])
            self.assertIn(1, report.failed_sequences)
            self.assertTrue(cache.has(hashes[0], verify=True))
            self.assertFalse(cache.has(hashes[1]))
            self.assertTrue(cache.has(hashes[2], verify=True))

    def test_corruption_recovery_retention_and_idle_restoration(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = ContentAddressedCache(Path(temporary) / "cache")
            pinned_raw = b"pinned" * 1000
            disposable_raw = b"disposable" * 1000
            pinned_hash = cache.put(pinned_raw, pinned=True)
            disposable_hash = cache.put(disposable_raw)
            path = cache.object_path(disposable_hash)
            data = bytearray(path.read_bytes())
            data[-3] ^= 0xFF
            path.write_bytes(data)
            with self.assertRaises(CacheCorruptionError):
                cache.get(disposable_hash)
            self.assertFalse(cache.has(disposable_hash))
            cache.put(disposable_raw)
            result = cache.maintenance(max_stored_bytes=cache.object_path(pinned_hash).stat().st_size)
            self.assertGreaterEqual(result["evicted"], 1)
            self.assertTrue(cache.has(pinned_hash, verify=True))
            controller = ActivityPolicyController()
            deep = controller.set_mode(ActivityMode.DEEP_IDLE)
            self.assertEqual(deep.max_concurrent_fetches, 0)
            self.assertFalse(deep.automatic_flush)
            active = controller.restore_active()
            self.assertEqual(active.max_concurrent_fetches, 8)
            self.assertTrue(active.automatic_flush)


if __name__ == "__main__":
    unittest.main(verbosity=2)
