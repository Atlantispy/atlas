"""Unit tests for direct bounded C1 climate reads and runoff bookkeeping."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from stage6c5r_climate import (
    C1MonthlyClimateReader,
    ClimateMember,
    ClimateSourceBinding,
    RUNOFF_SEMANTICS,
    effective_runoff_proxy,
)


VARIABLES = (
    ("precipitation_mm", "precipitation_mm", 10.0),
    ("pet_mm", "pet_mm", 2.0),
    ("snowfall_we_mm", "snowfall_we_mm", 1.0),
    ("temperature_c", "temperature_c", 4.0),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_fixture(root: Path, *, break_pet_transform: bool = False) -> ClimateSourceBinding:
    members: list[ClimateMember] = []
    source_files: list[tuple[Path, str]] = []
    archive_root = "fixture-climate"
    transform = from_origin(1000.0, 2000.0, 100.0, 100.0)

    for key, token, base in VARIABLES:
        path = root / f"{key}.tif"
        field_transform = (
            from_origin(1050.0, 2000.0, 100.0, 100.0)
            if break_pet_transform and key == "pet_mm"
            else transform
        )
        profile = {
            "driver": "GTiff",
            "width": 5,
            "height": 4,
            "count": 12,
            "dtype": "float32",
            "transform": field_transform,
            "nodata": -9999.0,
        }
        data = np.empty((12, 4, 5), dtype=np.float32)
        for month in range(12):
            data[month] = np.float32(base + month)
        data[:, 0, 0] = -9999.0
        with rasterio.open(path, "w", **profile) as dataset:
            dataset.write(data)
            for band in range(1, 13):
                dataset.set_band_description(band, f"M{band:02d}_{token}")

        member_path = f"{archive_root}/data/monthly/{path.name}"
        members.append(
            ClimateMember(key, member_path, _sha256(path), path.stat().st_size, token)
        )
        source_files.append((path, member_path))

    archive_path = root / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for source, member_path in source_files:
            archive.write(source, member_path)
    return ClimateSourceBinding(
        archive_path=archive_path,
        archive_sha256=_sha256(archive_path),
        archive_size_bytes=archive_path.stat().st_size,
        members=tuple(members),
    )


class ClimateReaderTests(unittest.TestCase):
    def test_direct_vsizip_window_and_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binding = _build_fixture(Path(temporary))
            member_receipts = {member.key: member.sha256 for member in binding.members}
            with C1MonthlyClimateReader(
                binding,
                verified_archive_sha256=binding.archive_sha256,
                verified_member_sha256=member_receipts,
            ) as reader:
                climate = reader.read_window(Window(0, 0, 4, 3))
                self.assertEqual(climate.shape, (12, 3, 4))
                self.assertEqual(climate.precipitation_mm.dtype, np.dtype("float32"))
                self.assertFalse(climate.land_mask[0, 0])
                self.assertTrue(np.isnan(climate.precipitation_mm[:, 0, 0]).all())
                self.assertTrue(np.isfinite(climate.temperature_c[:, climate.land_mask]).all())
                self.assertEqual(climate.transform, from_origin(1000.0, 2000.0, 100.0, 100.0))
                self.assertEqual(
                    climate.source_lineage["archive_expected_sha256"], binding.archive_sha256
                )
                self.assertTrue(climate.source_lineage["archive_hash_receipt_present"])
                self.assertEqual(climate.source_lineage["runoff_semantics"], RUNOFF_SEMANTICS)
                with self.assertRaises(TypeError):
                    climate.source_lineage["archive_expected_sha256"] = "changed"

                self.assertEqual(reader.verify_archive_content_sha256(), binding.archive_sha256)

    def test_read_with_proxy_is_bounded_and_soil_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binding = _build_fixture(Path(temporary))
            with C1MonthlyClimateReader(binding) as reader:
                climate, proxy = reader.read_window_with_runoff_proxy(((1, 3), (1, 4)))
                self.assertEqual(climate.shape, (12, 2, 3))
                self.assertEqual(proxy.monthly_effective_runoff_mm.shape, (12, 2, 3))
                self.assertEqual(proxy.semantics, RUNOFF_SEMANTICS)
                self.assertIn("NOT_OBSERVED", proxy.semantics)
                with self.assertRaises(ValueError):
                    reader.read_window(((3, 5), (1, 4)))

    def test_snow_carry_melt_and_pet_bookkeeping(self) -> None:
        shape = (12, 1, 2)
        precipitation = np.zeros(shape, dtype=np.float32)
        pet = np.zeros(shape, dtype=np.float32)
        snow = np.zeros(shape, dtype=np.float32)
        temperature = np.full(shape, -5.0, dtype=np.float32)
        precipitation[0] = 10.0
        snow[0] = 10.0
        temperature[2] = 1.0
        pet[2, 0, 1] = 2.0

        result = effective_runoff_proxy(
            precipitation,
            pet,
            snow,
            temperature,
            melt_factor_mm_per_degree_c_month=6.0,
        )
        np.testing.assert_array_equal(result.monthly_effective_runoff_mm[:2], 0.0)
        np.testing.assert_allclose(result.monthly_snowmelt_mm[2], [[6.0, 6.0]])
        np.testing.assert_allclose(result.monthly_effective_runoff_mm[2], [[6.0, 4.0]])
        np.testing.assert_allclose(result.monthly_snowpack_mm[2], [[4.0, 4.0]])
        np.testing.assert_allclose(result.ending_snowpack_mm, [[4.0, 4.0]])

    def test_structure_and_receipts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binding = _build_fixture(Path(temporary), break_pet_transform=True)
            with self.assertRaisesRegex(ValueError, "transform mismatch"):
                with C1MonthlyClimateReader(binding):
                    pass
            with self.assertRaisesRegex(ValueError, "archive receipt"):
                with C1MonthlyClimateReader(binding, verified_archive_sha256="0" * 64):
                    pass
            first = binding.members[0]
            with self.assertRaisesRegex(ValueError, first.key):
                with C1MonthlyClimateReader(
                    binding, verified_member_sha256={first.key: "0" * 64}
                ):
                    pass


if __name__ == "__main__":
    unittest.main()
