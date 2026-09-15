"""Bounded C1 climate reads for the Stage 6C.5R review-only model.

The four 100 m monthly rasters are read directly from their immutable ZIP
package through GDAL's ``/vsizip/`` virtual filesystem.  Nothing is extracted
and the 33 GB archive is never hashed in the hot window-read path.  Instead,
this module binds the exact package and member SHA-256 values and can consume
hash receipts produced by the generator's verified-source cache.

The effective-runoff calculation in this module is deliberately modest.  It
is a deterministic, soil-free bookkeeping proxy for comparing monthly water
availability.  It is neither observed runoff nor authoritative hydrology.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence
import zipfile

import numpy as np
import rasterio
from affine import Affine
from rasterio.windows import Window


MODEL_STATUS = "WORKING PROPOSAL - REVIEW ONLY - NOT CANON"
METHOD_VERSION = "S6C5R_BOUNDED_C1_CLIMATE_ADAPTER_1.0.0"
RUNOFF_SEMANTICS = (
    "DETERMINISTIC_SOIL_FREE_EFFECTIVE_RUNOFF_PROXY_REVIEW_ONLY_NOT_OBSERVED_"
    "NOT_AUTHORITATIVE"
)

DEFAULT_ARCHIVE_PATH = Path(
    r"C:\Users\LOCAL_USER\Documents\Codex\2026-07-11\referenced-chatgpt-conversation-this-is-untrusted"
    r"\outputs\Diadem_C1_100m_Full_Climate_Production_Review_2026-08-03.zip"
)
DEFAULT_ARCHIVE_SHA256 = "587d96bb09850a694fd2e5265fbb793f1ad9f6a4cc2e8330ad7aafa649961659"
DEFAULT_ARCHIVE_BYTES = 33_176_576_188
_ARCHIVE_ROOT = "Diadem_C1_100m_Full_Climate_Production_Review_2026-08-03"


@dataclass(frozen=True)
class ClimateMember:
    key: str
    member_path: str
    sha256: str
    size_bytes: int
    description_token: str


DEFAULT_MEMBERS = (
    ClimateMember(
        "precipitation_mm",
        f"{_ARCHIVE_ROOT}/data/monthly/c1-r1-monthly-precipitation-mm-review-only.tif",
        "08f16fe8f690764f9ef1b5894c8b8ec476a31dfa8d9201628bb0f57476a5312b",
        4_584_788_771,
        "precipitation_mm",
    ),
    ClimateMember(
        "pet_mm",
        f"{_ARCHIVE_ROOT}/data/monthly/c1-r1-monthly-pet-mm-review-only.tif",
        "d1a4507fb20f1d601b3fff9dbc5984888da99bfd8ce34c5ae41e2378b4b550c4",
        4_388_704_753,
        "pet_mm",
    ),
    ClimateMember(
        "snowfall_we_mm",
        f"{_ARCHIVE_ROOT}/data/monthly/c1-r1-monthly-snowfall-we-mm-review-only.tif",
        "b57f1e075ed53c2388f51b52d7151355bfd702690733e73ccbe5a0b36ddbc79e",
        2_578_496_950,
        "snowfall_we_mm",
    ),
    ClimateMember(
        "temperature_c",
        f"{_ARCHIVE_ROOT}/data/monthly/c1-r1-monthly-temperature-c-review-only.tif",
        "0f93652b65da92e9790593d1c53978c250d3d1670da2227ce7141d7b78bd7b6f",
        5_923_161_791,
        "temperature_c",
    ),
)


def _validate_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase hexadecimal SHA-256")


@dataclass(frozen=True)
class ClimateSourceBinding:
    archive_path: Path
    archive_sha256: str
    archive_size_bytes: int
    members: tuple[ClimateMember, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "archive_path", Path(self.archive_path))
        _validate_sha256(self.archive_sha256, "archive_sha256")
        if self.archive_size_bytes <= 0:
            raise ValueError("archive_size_bytes must be positive")
        keys = [member.key for member in self.members]
        if len(keys) != len(set(keys)) or set(keys) != {
            "precipitation_mm",
            "pet_mm",
            "snowfall_we_mm",
            "temperature_c",
        }:
            raise ValueError("binding must contain exactly the four required climate members")
        for member in self.members:
            _validate_sha256(member.sha256, f"member {member.key} sha256")
            if member.size_bytes <= 0:
                raise ValueError(f"member {member.key} size_bytes must be positive")


DEFAULT_BINDING = ClimateSourceBinding(
    DEFAULT_ARCHIVE_PATH,
    DEFAULT_ARCHIVE_SHA256,
    DEFAULT_ARCHIVE_BYTES,
    DEFAULT_MEMBERS,
)


@dataclass(frozen=True)
class ClimateWindow:
    precipitation_mm: np.ndarray
    pet_mm: np.ndarray
    snowfall_we_mm: np.ndarray
    temperature_c: np.ndarray
    land_mask: np.ndarray
    transform: Affine
    window: Window
    source_lineage: Mapping[str, object]

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.precipitation_mm.shape


@dataclass(frozen=True)
class EffectiveRunoffProxy:
    monthly_effective_runoff_mm: np.ndarray
    monthly_snowmelt_mm: np.ndarray
    monthly_snowpack_mm: np.ndarray
    ending_snowpack_mm: np.ndarray
    semantics: str = RUNOFF_SEMANTICS
    model_status: str = MODEL_STATUS


def _normalise_window(window: Window | Sequence[Sequence[int]]) -> Window:
    if isinstance(window, Window):
        candidate = window
    else:
        try:
            rows, columns = window
            row0, row1 = rows
            col0, col1 = columns
        except (TypeError, ValueError) as error:
            raise TypeError("window must be a rasterio Window or ((row0,row1),(col0,col1))") from error
        candidate = Window(col0, row0, col1 - col0, row1 - row0)

    values = (candidate.col_off, candidate.row_off, candidate.width, candidate.height)
    if any(not float(value).is_integer() for value in values):
        raise ValueError("climate windows must use integer pixel offsets and dimensions")
    candidate = Window(*(int(value) for value in values))
    if candidate.col_off < 0 or candidate.row_off < 0:
        raise ValueError("climate window offsets must be non-negative")
    if candidate.width <= 0 or candidate.height <= 0:
        raise ValueError("climate window dimensions must be positive")
    return candidate


def _vsi_path(archive_path: Path, member_path: str) -> str:
    archive = archive_path.resolve().as_posix()
    return f"/vsizip/{archive}/{member_path}"


def _hash_file(path: Path, chunk_bytes: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_bytes), b""):
            digest.update(chunk)
    return digest.hexdigest()


class C1MonthlyClimateReader:
    """Context-managed direct reader for bounded monthly climate windows.

    ``verified_archive_sha256`` and ``verified_member_sha256`` are optional
    receipts from the existing source-hash cache.  If supplied they must match
    the immutable binding.  Their absence is represented honestly in lineage;
    it never causes the reader to imply that full content hashing occurred.
    """

    def __init__(
        self,
        binding: ClimateSourceBinding = DEFAULT_BINDING,
        *,
        verified_archive_sha256: str | None = None,
        verified_member_sha256: Mapping[str, str] | None = None,
    ) -> None:
        self.binding = binding
        self._verified_archive_sha256 = verified_archive_sha256
        self._verified_member_sha256 = dict(verified_member_sha256 or {})
        self._stack: ExitStack | None = None
        self._datasets: dict[str, rasterio.io.DatasetReader] = {}
        self._lineage: Mapping[str, object] | None = None

    def __enter__(self) -> "C1MonthlyClimateReader":
        if self._stack is not None:
            raise RuntimeError("reader is already open")
        self._validate_receipts()
        self._validate_archive_directory()
        stack = ExitStack()
        try:
            datasets = {
                member.key: stack.enter_context(
                    rasterio.open(_vsi_path(self.binding.archive_path, member.member_path))
                )
                for member in self.binding.members
            }
            self._validate_rasters(datasets)
        except BaseException:
            stack.close()
            raise
        self._stack = stack
        self._datasets = datasets
        self._lineage = self._make_lineage()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._stack is not None:
            self._stack.close()
        self._stack = None
        self._datasets = {}
        self._lineage = None

    @property
    def source_lineage(self) -> Mapping[str, object]:
        if self._lineage is None:
            raise RuntimeError("reader is not open")
        return self._lineage

    def verify_archive_content_sha256(self) -> str:
        """Explicitly stream-hash the complete archive outside the hot path."""

        actual = _hash_file(self.binding.archive_path)
        if actual != self.binding.archive_sha256:
            raise ValueError(
                f"archive SHA-256 mismatch: expected {self.binding.archive_sha256}, got {actual}"
            )
        return actual

    def read_window(self, window: Window | Sequence[Sequence[int]]) -> ClimateWindow:
        if not self._datasets:
            raise RuntimeError("reader must be used inside a context manager")
        bounded = _normalise_window(window)
        reference = self._datasets["precipitation_mm"]
        if (
            bounded.col_off + bounded.width > reference.width
            or bounded.row_off + bounded.height > reference.height
        ):
            raise ValueError("climate window falls outside the immutable source raster")

        arrays: dict[str, np.ndarray] = {}
        masks: dict[str, np.ndarray] = {}
        for key, dataset in self._datasets.items():
            raw = dataset.read(window=bounded, masked=True, out_dtype="float32")
            if raw.shape != (12, int(bounded.height), int(bounded.width)):
                raise RuntimeError(f"unexpected bounded read shape for {key}: {raw.shape}")
            mask = ~np.ma.getmaskarray(raw).any(axis=0)
            data = np.asarray(raw.filled(np.nan), dtype=np.float32)
            if not np.isfinite(data[:, mask]).all():
                raise ValueError(f"{key} contains non-finite values on valid land cells")
            arrays[key] = data
            masks[key] = mask

        land_mask = masks["precipitation_mm"]
        for key, mask in masks.items():
            if not np.array_equal(mask, land_mask):
                raise ValueError(f"valid-land mask disagrees between precipitation and {key}")

        transform = rasterio.windows.transform(bounded, reference.transform)
        return ClimateWindow(
            precipitation_mm=arrays["precipitation_mm"],
            pet_mm=arrays["pet_mm"],
            snowfall_we_mm=arrays["snowfall_we_mm"],
            temperature_c=arrays["temperature_c"],
            land_mask=land_mask,
            transform=transform,
            window=bounded,
            source_lineage=self.source_lineage,
        )

    def read_window_with_runoff_proxy(
        self,
        window: Window | Sequence[Sequence[int]],
        **proxy_parameters: float | np.ndarray,
    ) -> tuple[ClimateWindow, EffectiveRunoffProxy]:
        climate = self.read_window(window)
        proxy = effective_runoff_proxy(
            climate.precipitation_mm,
            climate.pet_mm,
            climate.snowfall_we_mm,
            climate.temperature_c,
            land_mask=climate.land_mask,
            **proxy_parameters,
        )
        return climate, proxy

    def _validate_receipts(self) -> None:
        if (
            self._verified_archive_sha256 is not None
            and self._verified_archive_sha256 != self.binding.archive_sha256
        ):
            raise ValueError("verified archive receipt does not match the frozen binding")
        expected_members = {member.key: member.sha256 for member in self.binding.members}
        unknown = set(self._verified_member_sha256) - set(expected_members)
        if unknown:
            raise ValueError(f"verified member receipt contains unknown keys: {sorted(unknown)}")
        for key, actual in self._verified_member_sha256.items():
            if actual != expected_members[key]:
                raise ValueError(f"verified member receipt for {key} does not match the frozen binding")

    def _validate_archive_directory(self) -> None:
        path = self.binding.archive_path
        if not path.is_file():
            raise FileNotFoundError(path)
        actual_size = path.stat().st_size
        if actual_size != self.binding.archive_size_bytes:
            raise ValueError(
                f"archive byte-size mismatch: expected {self.binding.archive_size_bytes}, got {actual_size}"
            )
        with zipfile.ZipFile(path, "r") as archive:
            for member in self.binding.members:
                try:
                    info = archive.getinfo(member.member_path)
                except KeyError as error:
                    raise ValueError(f"missing frozen climate member: {member.member_path}") from error
                if info.file_size != member.size_bytes:
                    raise ValueError(
                        f"member byte-size mismatch for {member.key}: "
                        f"expected {member.size_bytes}, got {info.file_size}"
                    )
                if info.compress_type != zipfile.ZIP_STORED:
                    raise ValueError(
                        f"{member.key} is not stored uncompressed; bounded /vsizip/ access would not be safe"
                    )

    def _validate_rasters(self, datasets: Mapping[str, rasterio.io.DatasetReader]) -> None:
        reference = datasets["precipitation_mm"]
        expected_shape = (reference.height, reference.width)
        expected_transform = reference.transform
        expected_crs = reference.crs
        expected_nodata = reference.nodata
        for member in self.binding.members:
            dataset = datasets[member.key]
            if dataset.count != 12:
                raise ValueError(f"{member.key} must contain exactly 12 monthly bands")
            if dataset.shape != expected_shape:
                raise ValueError(f"raster shape mismatch for {member.key}")
            if dataset.transform != expected_transform:
                raise ValueError(f"raster transform mismatch for {member.key}")
            if dataset.crs != expected_crs:
                raise ValueError(f"raster CRS mismatch for {member.key}")
            if dataset.nodata != expected_nodata or dataset.nodata is None:
                raise ValueError(f"raster nodata mismatch for {member.key}")
            if any(dtype != "float32" for dtype in dataset.dtypes):
                raise ValueError(f"{member.key} must contain Float32 bands")
            descriptions = dataset.descriptions
            if len(descriptions) != 12 or any(
                not description or member.description_token not in description.lower()
                for description in descriptions
            ):
                raise ValueError(f"monthly band descriptions are invalid for {member.key}")

    def _make_lineage(self) -> Mapping[str, object]:
        members = tuple(
            MappingProxyType(
                {
                    "key": member.key,
                    "member_path": member.member_path,
                    "expected_sha256": member.sha256,
                    "expected_size_bytes": member.size_bytes,
                    "hash_receipt_present": member.key in self._verified_member_sha256,
                }
            )
            for member in self.binding.members
        )
        lineage = {
            "schema_version": "1.0.0-stage6c5r-climate-lineage",
            "model_status": MODEL_STATUS,
            "nominal_resolution_m": 100,
            "archive_path": str(self.binding.archive_path),
            "archive_expected_sha256": self.binding.archive_sha256,
            "archive_expected_size_bytes": self.binding.archive_size_bytes,
            "archive_hash_receipt_present": self._verified_archive_sha256 is not None,
            "members": members,
            "integrity_mode": (
                "PINNED_SHA256_BINDINGS_PLUS_ZIP_DIRECTORY_AND_RASTER_STRUCTURE; "
                "CONTENT_HASH_RECEIPTS_FROM_VERIFIED_SOURCE_CACHE_WHEN_SUPPLIED"
            ),
            "runoff_semantics": RUNOFF_SEMANTICS,
        }
        return MappingProxyType(lineage)


def effective_runoff_proxy(
    precipitation_mm: np.ndarray,
    pet_mm: np.ndarray,
    snowfall_we_mm: np.ndarray,
    temperature_c: np.ndarray,
    *,
    land_mask: np.ndarray | None = None,
    initial_snowpack_mm: float | np.ndarray = 0.0,
    melt_factor_mm_per_degree_c_month: float = 30.0,
    melt_threshold_c: float = 0.0,
) -> EffectiveRunoffProxy:
    """Compute a transparent monthly water-availability proxy.

    Precipitation is treated as total water input.  Snowfall-water-equivalent
    is subtracted before liquid precipitation is calculated, carried in a
    snowpack, and released using a bounded degree-month melt rule.  PET is then
    subtracted directly.  There is intentionally no soil, infiltration,
    aquifer, routing, storage or baseflow model.
    """

    fields = [
        np.asarray(precipitation_mm, dtype=np.float32),
        np.asarray(pet_mm, dtype=np.float32),
        np.asarray(snowfall_we_mm, dtype=np.float32),
        np.asarray(temperature_c, dtype=np.float32),
    ]
    if any(field.ndim < 2 or field.shape[0] != 12 for field in fields):
        raise ValueError("all climate inputs must be 12-band arrays")
    if any(field.shape != fields[0].shape for field in fields[1:]):
        raise ValueError("all climate inputs must have identical shapes")
    if melt_factor_mm_per_degree_c_month < 0:
        raise ValueError("melt factor must be non-negative")

    spatial_shape = fields[0].shape[1:]
    if land_mask is None:
        mask = np.ones(spatial_shape, dtype=bool)
    else:
        mask = np.asarray(land_mask, dtype=bool)
        if mask.shape != spatial_shape:
            raise ValueError("land_mask shape must match the climate spatial shape")

    precipitation, pet, snowfall, temperature = fields
    for name, field in (
        ("precipitation", precipitation),
        ("PET", pet),
        ("snowfall", snowfall),
        ("temperature", temperature),
    ):
        if not np.isfinite(field[:, mask]).all():
            raise ValueError(f"{name} contains non-finite land values")
    tolerance = np.float32(1e-3)
    if np.any(precipitation[:, mask] < -tolerance):
        raise ValueError("precipitation cannot be negative on land")
    if np.any(pet[:, mask] < -tolerance):
        raise ValueError("PET cannot be negative on land")
    if np.any(snowfall[:, mask] < -tolerance):
        raise ValueError("snowfall cannot be negative on land")
    if np.any(snowfall[:, mask] - precipitation[:, mask] > tolerance):
        raise ValueError("snowfall-water-equivalent cannot exceed total precipitation")

    initial = np.asarray(initial_snowpack_mm, dtype=np.float32)
    if initial.ndim == 0:
        initial = np.full(spatial_shape, initial, dtype=np.float32)
    if initial.shape != spatial_shape:
        raise ValueError("initial_snowpack_mm must be scalar or match the spatial shape")
    if not np.isfinite(initial[mask]).all() or np.any(initial[mask] < 0):
        raise ValueError("initial snowpack must be finite and non-negative on land")

    runoff = np.full(fields[0].shape, np.nan, dtype=np.float32)
    melt_series = np.full(fields[0].shape, np.nan, dtype=np.float32)
    pack_series = np.full(fields[0].shape, np.nan, dtype=np.float32)
    pack = np.where(mask, initial, np.nan).astype(np.float32, copy=False)

    for month in range(12):
        total = np.maximum(precipitation[month], 0.0)
        snow = np.minimum(np.maximum(snowfall[month], 0.0), total)
        liquid = total - snow
        pack = pack + snow
        melt_capacity = np.maximum(temperature[month] - melt_threshold_c, 0.0)
        melt_capacity = melt_capacity * np.float32(melt_factor_mm_per_degree_c_month)
        melt = np.minimum(pack, melt_capacity)
        pack = pack - melt
        available = liquid + melt
        monthly_runoff = np.maximum(available - np.maximum(pet[month], 0.0), 0.0)

        runoff[month] = np.where(mask, monthly_runoff, np.nan)
        melt_series[month] = np.where(mask, melt, np.nan)
        pack_series[month] = np.where(mask, pack, np.nan)

    return EffectiveRunoffProxy(
        monthly_effective_runoff_mm=runoff,
        monthly_snowmelt_mm=melt_series,
        monthly_snowpack_mm=pack_series,
        ending_snowpack_mm=pack.copy(),
    )


__all__ = [
    "C1MonthlyClimateReader",
    "ClimateMember",
    "ClimateSourceBinding",
    "ClimateWindow",
    "DEFAULT_ARCHIVE_BYTES",
    "DEFAULT_ARCHIVE_PATH",
    "DEFAULT_ARCHIVE_SHA256",
    "DEFAULT_BINDING",
    "DEFAULT_MEMBERS",
    "EffectiveRunoffProxy",
    "MODEL_STATUS",
    "RUNOFF_SEMANTICS",
    "effective_runoff_proxy",
]
