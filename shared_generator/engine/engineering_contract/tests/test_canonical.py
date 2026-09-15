from __future__ import annotations

import json
from pathlib import Path
import unittest

from diadem_contract.adapters import fingerprint_lineage, fingerprint_manifest, future_cache_key
from diadem_contract.canonical import canonical_json_bytes, semantic_fingerprint
from diadem_contract.ids import layer_id, resolution_id, tile_id


ROOT = Path(__file__).resolve().parents[1]


class CanonicalFingerprintTests(unittest.TestCase):
    def test_json_key_order_is_invariant(self):
        first = {"b": [2, 3], "a": {"z": 1, "x": "yes"}}
        second = {"a": {"x": "yes", "z": 1}, "b": [2, 3]}
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(semantic_fingerprint("generic", first), semantic_fingerprint("generic", second))

    def test_unicode_nfc_is_invariant(self):
        self.assertEqual(canonical_json_bytes("e\u0301"), canonical_json_bytes("é"))

    def test_type_tags_separate_equal_content(self):
        value = {"same": True}
        self.assertNotEqual(semantic_fingerprint("manifest", value), semantic_fingerprint("lineage", value))

    def test_manifest_is_invariant_to_paths_timestamps_compression_and_record_order(self):
        first = json.loads((ROOT / "examples/adapters/manifest-a.json").read_text(encoding="utf-8"))
        second = json.loads((ROOT / "examples/adapters/manifest-b-equivalent.json").read_text(encoding="utf-8"))
        self.assertEqual(fingerprint_manifest(first), fingerprint_manifest(second))

    def test_semantic_manifest_change_changes_fingerprint(self):
        first = json.loads((ROOT / "examples/adapters/manifest-a.json").read_text(encoding="utf-8"))
        second = json.loads(json.dumps(first))
        second["files"][0]["semantic_fingerprint"] = "dgh:v1:raster:sha256:" + "e" * 64
        self.assertNotEqual(fingerprint_manifest(first), fingerprint_manifest(second))

    def test_lineage_transport_changes_are_invariant(self):
        first = json.loads((ROOT / "examples/adapters/lineage.example.json").read_text(encoding="utf-8"))
        second = json.loads(json.dumps(first))
        second["created_utc"] = "2040-01-01T00:00:00Z"
        second["sources"][0]["path"] = "Z:/moved/source.zarr"
        second["sources"][0]["compression"] = "zstd-19"
        self.assertEqual(fingerprint_lineage(first), fingerprint_lineage(second))

    def test_manifest_role_swap_changes_fingerprint(self):
        base = {
            "sources": [
                {
                    "source_id": "rain",
                    "role": "precipitation",
                    "path": "C:/a.tif",
                    "semantic_fingerprint": "dgh:v1:raster:sha256:" + "a" * 64,
                },
                {
                    "source_id": "heat",
                    "role": "temperature",
                    "path": "C:/b.tif",
                    "semantic_fingerprint": "dgh:v1:raster:sha256:" + "b" * 64,
                },
            ]
        }
        swapped = json.loads(json.dumps(base))
        swapped["sources"][0]["role"], swapped["sources"][1]["role"] = (
            swapped["sources"][1]["role"],
            swapped["sources"][0]["role"],
        )
        self.assertNotEqual(fingerprint_manifest(base), fingerprint_manifest(swapped))

    def test_transport_path_omission_requires_logical_identity_content_and_source_role(self):
        with self.assertRaisesRegex(ValueError, "logical ID"):
            fingerprint_manifest({"files": [{"path": "C:/x", "semantic_fingerprint": "dgh:v1:file:sha256:" + "a" * 64}]})
        with self.assertRaisesRegex(ValueError, "content fingerprint"):
            fingerprint_manifest({"files": [{"logical_id": "x", "path": "C:/x"}]})
        with self.assertRaisesRegex(ValueError, "semantic role"):
            fingerprint_manifest(
                {
                    "sources": [
                        {
                            "source_id": "x",
                            "path": "C:/x",
                            "semantic_fingerprint": "dgh:v1:file:sha256:" + "a" * 64,
                        }
                    ]
                }
            )

    def test_cache_key_is_input_order_invariant_but_parameter_sensitive(self):
        layer = layer_id("diadem", "elevation")
        resolution = resolution_id(10000)
        tile = tile_id(layer, resolution, 3, 4)
        recipe = str(semantic_fingerprint("recipe", {"version": 1}))
        input_a = str(semantic_fingerprint("raster", {"cells": 1}))
        input_b = str(semantic_fingerprint("vector", {"features": 2}))
        first = future_cache_key(
            recipe_fingerprint=recipe,
            input_fingerprints=[input_a, input_b],
            parameters={"threshold": 2},
            spatial_unit_id=tile,
            code_version="abc",
            schema_version="1",
        )
        second = future_cache_key(
            recipe_fingerprint=recipe,
            input_fingerprints=[input_b, input_a],
            parameters={"threshold": 2},
            spatial_unit_id=tile,
            code_version="abc",
            schema_version="1",
        )
        changed = future_cache_key(
            recipe_fingerprint=recipe,
            input_fingerprints=[input_a, input_b],
            parameters={"threshold": 3},
            spatial_unit_id=tile,
            code_version="abc",
            schema_version="1",
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)


if __name__ == "__main__":
    unittest.main()
