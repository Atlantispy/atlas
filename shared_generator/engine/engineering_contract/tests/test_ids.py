from __future__ import annotations

import unittest
import uuid

from diadem_contract.ids import (
    StructuredId,
    feature_id,
    layer_id,
    resolution_id,
    run_id,
    tile_id,
)


class StructuredIdentityTests(unittest.TestCase):
    def test_all_kinds_roundtrip_and_reencode_exactly(self):
        layer = layer_id("diadem", "elevation")
        resolution = resolution_id(10000)
        values = [
            layer,
            resolution,
            tile_id(layer, resolution, -12, 44, level=3),
            feature_id("diadem", "river-reach", "R-001"),
            run_id("diadem", uuid.UUID("12345678-1234-5678-1234-567812345678"), attempt=2),
        ]
        self.assertEqual([StructuredId.decode(value).encode() for value in values], values)
        self.assertEqual([StructuredId.decode(value).kind for value in values], ["layer", "resolution", "tile", "feature", "run"])

    def test_tile_decodes_nested_layer_resolution_and_coordinates(self):
        layer = layer_id("diadem", "hydrology")
        resolution = resolution_id(100000, 100000, 1000)
        encoded = tile_id(layer, resolution, 17, -9, level=2)
        decoded = StructuredId.decode(encoded)
        self.assertEqual(decoded.payload["layer"], layer)
        self.assertEqual(decoded.payload["resolution"], resolution)
        self.assertEqual((decoded.payload["x"], decoded.payload["y"], decoded.payload["level"]), (17, -9, 2))

    def test_type_separation_prevents_cross_kind_alias(self):
        layer = layer_id("diadem", "same")
        feature = feature_id("diadem", "same", "same")
        self.assertNotEqual(layer, feature)

    def test_large_sample_has_no_structured_id_collisions(self):
        layer = layer_id("diadem", "elevation")
        resolution = resolution_id(10000)
        observed = {
            tile_id(layer, resolution, index % 97, index // 97, level=index % 5)
            for index in range(10000)
        }
        self.assertEqual(len(observed), 10000)

    def test_noncanonical_and_wrong_nested_types_are_rejected(self):
        encoded = layer_id("diadem", "elevation")
        with self.assertRaises(ValueError):
            StructuredId.decode(encoded + "=")
        resolution = resolution_id(10000)
        with self.assertRaises(ValueError):
            tile_id(resolution, resolution, 0, 0)

    def test_booleans_are_not_accepted_as_integer_coordinates_or_resolutions(self):
        layer = layer_id("diadem", "elevation")
        resolution = resolution_id(10000)
        with self.assertRaises(ValueError):
            resolution_id(True)
        with self.assertRaises(ValueError):
            resolution_id(10000, vertical_mm=False)
        with self.assertRaises(ValueError):
            tile_id(layer, resolution, True, 0)
        with self.assertRaises(ValueError):
            tile_id(layer, resolution, 0, 0, level=False)
        with self.assertRaises(ValueError):
            run_id("diadem", uuid.uuid4(), attempt=True)


if __name__ == "__main__":
    unittest.main()
