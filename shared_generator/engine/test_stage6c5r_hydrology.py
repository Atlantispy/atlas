import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from shapely.geometry import LineString, box

from build_stage6c5r_physical_10m import sample_line_cells

from stage6c5r_hydrology import (
    ActiveMajorBedProfiles,
    downstream_order,
    enforce_strict_bed_drop,
    make_minor_bed_profile,
)


class ProfileAwareHydrologyTests(unittest.TestCase):
    def test_registered_axis_rasterisation_is_support_window_invariant(self):
        geometry = LineString([
            (10.005, 20.015),
            (10.513, 20.487),
            (11.027, 21.034),
        ])
        first = sample_line_cells(
            geometry,
            box(9.5, 19.5, 11.5, 21.5),
            1950,
            950,
            200,
            200,
        )
        shifted = sample_line_cells(
            geometry,
            box(9.6, 19.6, 11.6, 21.6),
            1960,
            960,
            200,
            200,
        )
        first_global = {
            (1950 + row, 950 + col)
            for part in first for row, col in part
            if 1980 <= 1950 + row < 2120 and 980 <= 950 + col < 1120
        }
        shifted_global = {
            (1960 + row, 960 + col)
            for part in shifted for row, col in part
            if 1980 <= 1960 + row < 2120 and 980 <= 960 + col < 1120
        }
        self.assertTrue(first_global)
        self.assertEqual(first_global, shifted_global)

    def test_chainage_sampling_does_not_zip_vertices(self):
        features = []
        for index in range(30):
            features.append({
                "type": "Feature",
                "properties": {"route_id": f"R{index}", "monotone_downstream": True},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0.0, float(index), 10.0], [1.0, float(index), 0.0]],
                },
            })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.geojson"
            path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
            profiles = ActiveMajorBedProfiles(path)
            sampled = profiles.sample_z("R0", [(0.25, 0.0), (0.75, 0.0)])
        np.testing.assert_allclose(sampled, [7.5, 2.5])

    def test_downstream_order_reverses_path_and_bed_together(self):
        path, bed = downstream_order(((0, 0), (0, 1)), (2.0, 8.0))
        self.assertEqual(path, ((0, 1), (0, 0)))
        self.assertEqual(bed, (8.0, 2.0))

    def test_minor_bed_is_separate_and_strictly_downstream(self):
        land = np.full((4, 4), 100.0)
        path, bed, lineage = make_minor_bed_profile(
            ((1, 0), (1, 1), (1, 2), (1, 3)),
            land,
            nominal_depth_m=0.2,
            median_slope_m_per_km=2.0,
            minimum_drop_m_per_cell=0.0001,
        )
        self.assertEqual(path[0], (1, 0))
        self.assertTrue(np.all(np.diff(np.asarray(bed)) < 0.0))
        self.assertTrue(np.allclose(land, 100.0))
        self.assertIn("NOT_OBSERVED_Z", str(lineage["vertical_control"]))

    def test_strict_drop_changes_only_flat_or_uphill_values(self):
        bed, maximum = enforce_strict_bed_drop((10.0, 9.0, 9.0, 8.0), 0.1)
        self.assertTrue(np.all(np.diff(np.asarray(bed)) <= -0.1 + 1e-12))
        self.assertAlmostEqual(maximum, 0.1)


if __name__ == "__main__":
    unittest.main()
