"""Read-only sealed-source bindings for the Diadem Stage 6C 100 m pass.

This module centralises the exact, audited source paths and immutable hashes used
by Stage 6C.  It deliberately does not create, extract, update, or repair any
source.  Several filenames still say ``review-only`` even where a later approval
record promotes that exact hash, so consumers must use the status and hash here
rather than infer authority from a filename.

Editable elevation is resolved separately by ``stage6c_terrain_authority``.
The two terrain TIFF records below are retained solely to validate generation-0
lineage and are never reopened to compose runtime terrain.

Coordinates are local Cartesian kilometres unless a source entry says
otherwise.  There is no geographic/EPSG CRS for the 100 m and 1 km grids.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from source_catalogue import generator_root, source_path

PROJECT_ROOT = generator_root()
# Kept as a compatibility constant for callers that imported it.  Active source
# resolution no longer consults a historical checkout.
LEGACY_ROOT = PROJECT_ROOT

# Sealed generation-0 terrain lineage plus the active sea-domain mask.
TERRAIN_D31_100M = source_path("terrain_d31_100m")
TERRAIN_D31_APPROVAL = source_path("terrain_d31_approval")
OBSIDIAN_SEA_MASK_100M = source_path("obsidian_sea_mask_100m")

# Sealed Stillklinge terrain lineage; flood remains an active local override.
STILLKLINGE_TERRAIN_100M = source_path("stillklinge_terrain_100m")
STILLKLINGE_FLOOD_100M = source_path("stillklinge_flood_100m")
STILLKLINGE_CANDIDATE_B_ROOT = STILLKLINGE_TERRAIN_100M.parent

# Protected 100 m special-water masks and H2.2 resolved water evidence.
MOORWANDLER_CORE_WETLAND_100M = source_path("moorwandler_core_wetland_100m")
SERENAKRONE_WATER_100M = source_path("serenakrone_water_100m")
H22_FLOOD_CANDIDATES_100M = source_path("h22_flood_candidates_100m")
H22_ACTIVE_L1_LAKES = source_path("h22_active_l1_lakes")
H22_ACTIVE_LEGACY_C1_LAKES = source_path("h22_active_legacy_c1_lakes")
H22_ACTIVE_LEGACY_CONNECTORS = source_path("h22_active_legacy_connectors")
H22_SEASONAL_L1_BASINS = source_path("h22_seasonal_l1_basins")
H22_ORDINARY_FLOODPLAINS = source_path("h22_ordinary_floodplains")
H22_MOORWANDLER_TRANSITION = source_path("h22_moorwandler_transition")
H22_LAKE_NAMESPACE_ROOT = H22_ACTIVE_L1_LAKES.parent
H22_VECTOR_ROOT = H22_ORDINARY_FLOODPLAINS.parent

# Current V4.2 vector composition. The 3,177-feature file is retained as exact
# parent-preserving lineage; the sealed runtime minor network is D3 outside
# Stillklinge plus the corrected 112-feature Stillklinge local composition.
V42_MANIFEST = source_path("v42_manifest")
V42_ACTIVE_MAJOR = source_path("v42_active_major")
V42_ACTIVE_MAJOR_BED_PROFILES = source_path("v42_active_major_bed_profiles")
V42_ACTIVE_MINOR = source_path("v42_active_minor")
V42_D3_RAW = source_path("v42_d3_raw")
V42_D3_ENRICHED = source_path("v42_d3_enriched")
V42_ACTIVE_SPECIAL = source_path("v42_active_special")
V42_STILLKLINGE_REPAIRED_MAJOR = source_path("v42_stillklinge_repaired_major")
V42_STILLKLINGE_LOCAL_112 = source_path("v42_stillklinge_local_112")
V42_SIDECAR_ROOT = V42_MANIFEST.parent
V42_DATA_ROOT = V42_ACTIVE_MAJOR.parent
V42_STILLKLINGE_QUARANTINE = (
    V42_DATA_ROOT / "v4-2-quarantined-stillklinge-d3-review-only.csv"
)
STILLKLINGE_APPROVAL = source_path("stillklinge_approval")

# Exact surface topology and exact fragment-to-barony assignment.
EXACT_SURFACE_REGISTRY = source_path("exact_surface_registry")
FRAGMENT_BARONY_ID = source_path("fragment_barony_id")

# Operational Stage 6B map and the V11 political source masks behind it.
STAGE6B_PROVINCE_GPKG = source_path("stage6b_province_gpkg")
POLITICAL_HAUS_V11 = source_path("political_haus_v11")
POLITICAL_COUNTY_V11 = source_path("political_county_v11")
POLITICAL_DUCHY_V11 = source_path("political_duchy_v11")
POLITICAL_V11_ROOT = POLITICAL_HAUS_V11.parent


LOCAL_CRS = "LOCAL_CARTESIAN_KM_NO_EPSG"
FULL_FRAME_RASTER_SHAPE = (18_600, 22_000)  # rows, columns
FULL_FRAME_100M_RESOLUTION_KM = 0.1
CARRIER_SHAPE = (1_860, 2_200)  # rows, columns
CARRIER_RESOLUTION_KM = 1.0
EXACT_FRAGMENT_COUNT = 2_494_913
BARONY_COUNT = 7_318

# These eight D3 reaches are excluded from the active 112-feature Stillklinge
# support layer until terrain-grounded repair or rejection.
STILLKLINGE_QUARANTINED_D3_IDS = frozenset(
    {
        "D3-MIN-013654",
        "D3-MIN-013664",
        "D3-MIN-013676",
        "D3-MIN-013700",
        "D3-MIN-013701",
        "D3-MIN-013711",
        "D3-MIN-013712",
        "D3-MIN-013713",
    }
)
STILLKLINGE_GRADE_PERSISTENCE_REVIEW_ID = "D3-MIN-013681"


@dataclass(frozen=True)
class SourceSpec:
    """Immutable expected metadata for one source file."""

    path: Path
    sha256: str
    kind: str
    status: str
    count: int | Mapping[str, int] | None = None
    shape: tuple[int, ...] | None = None
    resolution_km: float | None = None
    crs: str | None = LOCAL_CRS
    notes: str = ""

    def serialisable(self) -> dict[str, Any]:
        row = asdict(self)
        row["path"] = str(self.path)
        return row


APPROVED_TERRAIN = "APPROVED_AUTHORITATIVE_TERRAIN_PARENT"
APPROVED_LOCAL_OVERRIDE = "APPROVED_LOCAL_OVERRIDE_REGISTERED_FOOTPRINT_ONLY"
SEALED_TERRAIN_LINEAGE = "SEALED_GENERATION_0_TERRAIN_LINEAGE_ONLY"
FORMATION_REVIEW = "FORMATION_AUTHORITY_REVIEW_ONLY_NOT_CANON"
WORKING_REVIEW = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
H22_REVIEW = "CLOSED_REVIEW_ONLY_PENDING_MICHAEL"
V42_REVIEW = "SEALED_TECHNICAL_PASS_REVIEW_ONLY_NOT_CANON"
V42_APPROVED_CORE = "APPROVED_CANDIDATE_B_CORE_IN_REVIEW_ONLY_V4_2_ASSEMBLY"
V42_MIXED_112 = "MIXED_21_APPROVED_FLOOR_PLUS_91_REVIEW_ONLY_UNRESOLVED_CAPPED"


SOURCE_SPECS: Mapping[str, SourceSpec] = {
    "terrain_d31_100m": SourceSpec(
        TERRAIN_D31_100M,
        "fbaa09175c039d68993a83dbf2df3cd5835b8128386d7bc981eb13958907f3a7",
        "raster",
        SEALED_TERRAIN_LINEAGE,
        count=1,
        shape=FULL_FRAME_RASTER_SHAPE,
        resolution_km=FULL_FRAME_100M_RESOLUTION_KM,
        notes="Immutable generation-0 TIFF lineage; runtime elevation comes only from the editable Zarr authority.",
    ),
    "obsidian_sea_mask_100m": SourceSpec(
        OBSIDIAN_SEA_MASK_100M,
        "83e09b5fe4f3007c1e9600eee4870e4d42242f0bdcf36046411987bfb90ff943",
        "raster",
        "H1_1_PROTECTED_LAND_WATER_DOMAIN_BOUND_BY_D31_AND_EXACT_SURFACE",
        count=1,
        shape=FULL_FRAME_RASTER_SHAPE,
        resolution_km=FULL_FRAME_100M_RESOLUTION_KM,
    ),
    "stillklinge_terrain_100m": SourceSpec(
        STILLKLINGE_TERRAIN_100M,
        "dc5af05d10e212c26daf15daf8781334bfa80b626b0f1217c84f2bbdaf0b581f",
        "raster",
        SEALED_TERRAIN_LINEAGE,
        count=1,
        shape=(3_900, 1_550),
        resolution_km=FULL_FRAME_100M_RESOLUTION_KM,
        notes="Immutable generation-0 Stillklinge TIFF lineage already composed into the editable Zarr authority.",
    ),
    "stillklinge_flood_100m": SourceSpec(
        STILLKLINGE_FLOOD_100M,
        "b2e1b76f5833c1d407e69ef57ab091488d35087358b8e3ace7ab0e145f201bde",
        "raster",
        APPROVED_LOCAL_OVERRIDE,
        count=1,
        shape=(3_900, 1_550),
        resolution_km=FULL_FRAME_100M_RESOLUTION_KM,
        notes="Apply only inside the registered Stillklinge Candidate-B footprint.",
    ),
    "moorwandler_core_wetland_100m": SourceSpec(
        MOORWANDLER_CORE_WETLAND_100M,
        "7d53543784a45a893eee7fab5f2b531f8d229fb3d30108524c48fa637e7a3a3f",
        "raster",
        H22_REVIEW,
        count=1,
        shape=FULL_FRAME_RASTER_SHAPE,
        resolution_km=FULL_FRAME_100M_RESOLUTION_KM,
        notes="Exact irregular protected mask; never replace with the stale circular control.",
    ),
    "serenakrone_water_100m": SourceSpec(
        SERENAKRONE_WATER_100M,
        "5271ca6aa9582682ccb88c56815371af213dc9180d1941db85a23278c2b0293c",
        "raster",
        H22_REVIEW,
        count=1,
        shape=FULL_FRAME_RASTER_SHAPE,
        resolution_km=FULL_FRAME_100M_RESOLUTION_KM,
        notes="Protected tarn and lagoon mask; five coded water classes.",
    ),
    "h22_flood_candidates_100m": SourceSpec(
        H22_FLOOD_CANDIDATES_100M,
        "535a7165ba03ffb66e19c6aa1ad94ac21d10fbb5edc096d1c4649d1ecafc3e8e",
        "raster",
        H22_REVIEW,
        count=1,
        shape=FULL_FRAME_RASTER_SHAPE,
        resolution_km=FULL_FRAME_100M_RESOLUTION_KM,
        notes="Geomorphic candidate classes, not return-period inundation boundaries.",
    ),
    "h22_active_l1_lakes": SourceSpec(
        H22_ACTIVE_L1_LAKES,
        "084cb35aa4c35989c9b0428344ea8bdccc7544c3afb87b0cc4a6b4798e0b27d5",
        "geojson",
        H22_REVIEW,
        count=486,
        notes="Resolved active L1 namespace; maximum spill-sill footprints.",
    ),
    "h22_active_legacy_c1_lakes": SourceSpec(
        H22_ACTIVE_LEGACY_C1_LAKES,
        "0f9e7559df83dd27684a186a5303d849a87326f4de572dbf5e951d7119f89c8f",
        "geojson",
        H22_REVIEW,
        count=11,
        notes="Resolved retained legacy C1 lakes.",
    ),
    "h22_active_legacy_connectors": SourceSpec(
        H22_ACTIVE_LEGACY_CONNECTORS,
        "01596cd39da84cf6959b42e006bf53bfe4041c179d0aa5a49a445f8aa2ab45d0",
        "geojson",
        H22_REVIEW,
        count=11,
    ),
    "h22_seasonal_l1_basins": SourceSpec(
        H22_SEASONAL_L1_BASINS,
        "8b335adb410f356a7c3ab07dbdfb2e3835f5df8571b5566795fea44c9ca657a4",
        "geojson",
        H22_REVIEW,
        count=1_170,
        notes="Seasonal/nonpermanent display footprints.",
    ),
    "h22_ordinary_floodplains": SourceSpec(
        H22_ORDINARY_FLOODPLAINS,
        "ca356b3f57258c46e5c30f19c5ffc2e729e3978536fe7ff21b97987c4dd0f192",
        "geojson",
        H22_REVIEW,
        count=767,
        notes="Geomorphic candidates, not return-period flood polygons.",
    ),
    "h22_moorwandler_transition": SourceSpec(
        H22_MOORWANDLER_TRANSITION,
        "bf60990287737240db0ecdf2fd0dab488bf36ca802c2f0d2a2c3661970c70b7c",
        "geojson",
        H22_REVIEW,
        count=158,
        notes="Persistent wet edge and seasonal transition, not a flood-frequency map.",
    ),
    "v42_active_major": SourceSpec(
        V42_ACTIVE_MAJOR,
        "228f42f37599b6b99ce747c160e7a76574a0fe63623e8b791a7ff70c4a65eca3",
        "geojson",
        V42_REVIEW,
        count=30,
        notes="28 unchanged axes plus the two repaired BC-003 axes.",
    ),
    "v42_active_major_bed_profiles": SourceSpec(
        V42_ACTIVE_MAJOR_BED_PROFILES,
        "cb597ba4e4e6ceccc1efd3418f104b4cc2622fc301dea49dee4ca3e9b10d4dd4",
        "geojson",
        V42_REVIEW,
        count=30,
        notes=(
            "Three-dimensional monotone bed profiles paired to the active V4.2 major axes by "
            "route_id and planimetric chainage; includes Candidate-B BC-003 upper/lower profiles."
        ),
    ),
    "v42_active_minor": SourceSpec(
        V42_ACTIVE_MINOR,
        "707740a4a9dd488d954a2e6cbd7848f81b6fc7cbc525f59fc892c7c8986d2429",
        "geojson",
        V42_REVIEW,
        count=3_177,
        notes="Parent-preserving 3,177-feature lineage; not the sealed V4.2 runtime feeder composition.",
    ),
    "v42_d3_raw": SourceSpec(
        V42_D3_RAW,
        "78af082efd432e7e5408d01aec058ed1777743086ba88fd833ae033dab7c4a06",
        "geojson",
        V42_REVIEW,
        count=16_468,
        notes=(
            "Exact D3 feeder geometry used by sealed V4.2; all 99 raw "
            "Stillklinge rows are replaced at runtime by the corrected local 112."
        ),
    ),
    "v42_d3_enriched": SourceSpec(
        V42_D3_ENRICHED,
        "f2c219f1ef738e512a7b49673b4005afe64659103eb4360629dea77cfc506337",
        "geojson",
        V42_REVIEW,
        count=16_468,
        notes="Persistence and Strahler classification paired by exact minor-ID order with V42_D3_RAW.",
    ),
    "v42_active_special": SourceSpec(
        V42_ACTIVE_SPECIAL,
        "97453c76cb55a42dce7329e1c757d3f25c1d3bee29854fda94ee9287ea101b3c",
        "geojson",
        V42_REVIEW,
        count=10,
        notes="Six protected surface controls and four Stillklinge controls.",
    ),
    "v42_stillklinge_repaired_major": SourceSpec(
        V42_STILLKLINGE_REPAIRED_MAJOR,
        "c44b15dbb855702230a7bb2bbf809c5f399792a23a9e589e4bce25c070f0d980",
        "geojson",
        V42_APPROVED_CORE,
        count=2,
        notes="Approved BC-003 upper/lower Candidate-B geometry in the V4.2 assembly.",
    ),
    "v42_stillklinge_local_112": SourceSpec(
        V42_STILLKLINGE_LOCAL_112,
        "24e3509048bd791bdf0e6d10dd5a8df5051f8280d0df581251ba5cc27acd83f9",
        "geojson",
        V42_MIXED_112,
        count=112,
        notes=(
            "21 approved Candidate-B/F4 floor plus 91 connected D3 geometries with "
            "unresolved persistence and 0.35 ecological/0.15 domestic ceilings."
        ),
    ),
    "exact_surface_registry": SourceSpec(
        EXACT_SURFACE_REGISTRY,
        "1986ff3bba8d87ab1c89eb1491fca7b941c8ef4eae8a6e2e1d07d4647c34d808",
        "npz",
        FORMATION_REVIEW,
        count={
            "fragments": EXACT_FRAGMENT_COUNT,
            "carrier_cells": 4_092_000,
            "positive_graph_edges": 4_982_169,
            "explicit_boundary_fragments": 14_857,
        },
        shape=(EXACT_FRAGMENT_COUNT,),
        resolution_km=CARRIER_RESOLUTION_KM,
        notes="Exact fragments and positive-boundary graph; 1 km carriers are lookup indices only.",
    ),
    "fragment_barony_id": SourceSpec(
        FRAGMENT_BARONY_ID,
        "6a993b8d6670c1ab044854f94dbaa169daefbb7b6870b63655dd75c264637731",
        "npy",
        "COMPLETE_REVIEW_CANDIDATE_NOT_CANON_EXACT_FRAGMENT_ASSIGNMENT",
        count=EXACT_FRAGMENT_COUNT,
        shape=(EXACT_FRAGMENT_COUNT,),
        crs=None,
        notes="Extracted immutable member; int32 barony IDs 1..7318, one per exact fragment.",
    ),
    "stage6b_province_gpkg": SourceSpec(
        STAGE6B_PROVINCE_GPKG,
        "dd5e29ac5d85c74abb461a6a7249be94bf4da0ecdf2cf80d1af30d7454e9a37e",
        "gpkg",
        WORKING_REVIEW,
        count={
            "province": 7_318,
            "county": 1_177,
            "duchy": 211,
            "settlement": 31_271,
            "selected_seats": 19,
            "duftfaehrte_capital_anchors": 8,
        },
        notes="Operational joins and attributes only; exact borders come from fragment membership.",
    ),
    "political_haus_v11": SourceSpec(
        POLITICAL_HAUS_V11,
        "075930ef63a3ce2f3c8c6d14674b1dace1f8653ff213c82cd472fe9afe4898ba",
        "gpkg",
        WORKING_REVIEW,
        count={"haus_surface_fills": 20, "barony_haus_assignments": 7_318},
    ),
    "political_county_v11": SourceSpec(
        POLITICAL_COUNTY_V11,
        "180267c6fa902ca8b4dd6516494dd181b1406cd917b76577a5f83a4cbf37e2af",
        "gpkg",
        WORKING_REVIEW,
        count={"counties": 1_177, "barony_county_assignments": 7_318},
    ),
    "political_duchy_v11": SourceSpec(
        POLITICAL_DUCHY_V11,
        "fce774e18ae4ceb6a065c9425b1612dc79bd16b8af260e02f82db474cf1c13e8",
        "gpkg",
        WORKING_REVIEW,
        count={
            "duchies": 211,
            "county_duchy_assignments": 1_177,
            "barony_duchy_assignments": 7_318,
        },
    ),
}


def _io_path(path: str | os.PathLike[str]) -> Path:
    """Return a Windows extended-length path when the ordinary path is too long."""

    source = Path(path)
    if os.name != "nt":
        return source
    absolute = os.path.abspath(os.fspath(source))
    if absolute.startswith("\\\\?\\") or len(absolute) < 248:
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def sha256_file(path: str | os.PathLike[str], chunk_size: int = 8 * 1024 * 1024) -> str:
    """Return a lowercase SHA-256 digest without changing the file."""

    source = _io_path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sources(
    keys: Iterable[str] | None = None,
    *,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """Existence- and hash-check selected immutable inputs.

    The function is read-only.  ``keys=None`` verifies the entire active stack,
    including the large terrain raster.  A caller doing a quick preflight can
    pass a subset of ``SOURCE_SPECS`` keys.
    """

    selected = tuple(SOURCE_SPECS) if keys is None else tuple(keys)
    unknown = sorted(set(selected).difference(SOURCE_SPECS))
    if unknown:
        raise KeyError(f"Unknown Stage 6C source keys: {unknown}")

    results: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for key in selected:
        spec = SOURCE_SPECS[key]
        io_path = _io_path(spec.path)
        row: dict[str, Any] = {
            "path": str(spec.path),
            "expected_sha256": spec.sha256,
            "status": spec.status,
            "exists": io_path.is_file(),
        }
        if not row["exists"]:
            row.update(actual_sha256=None, size_bytes=None, ok=False, error="missing")
            failures.append(key)
        else:
            try:
                actual = sha256_file(spec.path)
                row.update(
                    actual_sha256=actual,
                    size_bytes=io_path.stat().st_size,
                    ok=actual == spec.sha256,
                    error=None if actual == spec.sha256 else "sha256_mismatch",
                )
            except OSError as exc:
                row.update(actual_sha256=None, size_bytes=None, ok=False, error=str(exc))
            if not row["ok"]:
                failures.append(key)
        results[key] = row

    report = {
        "ok": not failures,
        "checked_count": len(selected),
        "failed_keys": failures,
        "results": results,
    }
    if failures and raise_on_error:
        raise RuntimeError(f"Stage 6C source verification failed: {failures}")
    return report


def source_manifest_rows() -> list[dict[str, Any]]:
    """Return stable, JSON-serialisable source-manifest rows."""

    return [
        {"source_key": key, **SOURCE_SPECS[key].serialisable()}
        for key in sorted(SOURCE_SPECS)
    ]


def read_geojson_geometries(
    path: str | os.PathLike[str],
    *,
    include_properties: bool = False,
) -> Iterator[Any]:
    """Yield raw GeoJSON geometries, optionally paired with properties.

    Raw geometry mappings are returned deliberately so this authority layer has
    no Shapely/GeoPandas import requirement.  FeatureCollection, Feature,
    GeometryCollection, and bare-geometry roots are supported.
    """

    with Path(path).open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)

    root_type = payload.get("type")
    if root_type == "FeatureCollection":
        features = payload.get("features", ())
    elif root_type == "Feature":
        features = (payload,)
    elif root_type == "GeometryCollection":
        features = (
            {"type": "Feature", "properties": {}, "geometry": geometry}
            for geometry in payload.get("geometries", ())
        )
    else:
        features = ({"type": "Feature", "properties": {}, "geometry": payload},)

    for feature in features:
        geometry = feature.get("geometry")
        if geometry is None:
            continue
        if include_properties:
            yield geometry, dict(feature.get("properties") or {})
        else:
            yield geometry


_GPKG_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def gpkg_wkb(blob: bytes | bytearray | memoryview) -> bytes:
    """Strip a GeoPackage geometry header and return its standard WKB payload.

    Raises ``ValueError`` for non-GeoPackage blobs, reserved envelope codes, or
    truncated headers.  The function never mutates the supplied buffer.
    """

    data = memoryview(blob).cast("B")
    if len(data) < 9 or bytes(data[:2]) != b"GP":
        raise ValueError("Not a GeoPackage geometry blob")
    version = int(data[2])
    if version != 0:
        raise ValueError(f"Unsupported GeoPackage geometry version: {version}")
    flags = int(data[3])
    envelope_code = (flags >> 1) & 0b111
    try:
        envelope_bytes = _GPKG_ENVELOPE_BYTES[envelope_code]
    except KeyError as exc:
        raise ValueError(f"Reserved GeoPackage envelope code: {envelope_code}") from exc
    header_bytes = 8 + envelope_bytes
    if len(data) <= header_bytes:
        raise ValueError("Truncated GeoPackage geometry blob")
    wkb = bytes(data[header_bytes:])
    if wkb[0] not in (0, 1):
        raise ValueError("Invalid WKB byte-order marker after GeoPackage header")
    return wkb


class ExactSurfaceLookup:
    """Lazy, read-only carrier-cell and fragment-to-barony lookup.

    Fragment IDs are zero-based array indices.  A carrier-cell lookup returns
    every exact fragment intersecting that 1 km cell; it is not an exact point-
    in-polygon decision when a cell has multiple components.  ``boundary_wkb``
    exposes exact registered boundary geometry where it exists.
    """

    def __init__(
        self,
        registry_path: str | os.PathLike[str] = EXACT_SURFACE_REGISTRY,
        fragment_barony_path: str | os.PathLike[str] = FRAGMENT_BARONY_ID,
    ) -> None:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError("ExactSurfaceLookup requires NumPy") from exc

        self._np = np
        self.registry_path = Path(registry_path)
        self.fragment_barony_path = Path(fragment_barony_path)
        self._registry = np.load(self.registry_path, allow_pickle=False)
        self._barony = np.load(
            self.fragment_barony_path, mmap_mode="r", allow_pickle=False
        )
        self._cache: dict[str, Any] = {}
        if self._barony.shape != (EXACT_FRAGMENT_COUNT,):
            self.close()
            raise ValueError(f"Unexpected fragment_barony_id shape: {self._barony.shape}")
        offsets = self._array("cell_offsets")
        if offsets.shape != (CARRIER_SHAPE[0] * CARRIER_SHAPE[1] + 1,):
            self.close()
            raise ValueError(f"Unexpected cell_offsets shape: {offsets.shape}")
        if int(offsets[-1]) != EXACT_FRAGMENT_COUNT:
            self.close()
            raise ValueError(f"Unexpected final fragment offset: {int(offsets[-1])}")

    def _array(self, key: str) -> Any:
        if key not in self._cache:
            self._cache[key] = self._registry[key]
        return self._cache[key]

    @staticmethod
    def carrier_index(row: int, col: int) -> int:
        if not 0 <= row < CARRIER_SHAPE[0] or not 0 <= col < CARRIER_SHAPE[1]:
            raise IndexError(f"Carrier row/col outside {CARRIER_SHAPE}: {(row, col)}")
        return row * CARRIER_SHAPE[1] + col

    @staticmethod
    def carrier_row_col_for_xy(x_km: float, y_km: float) -> tuple[int, int]:
        if not math.isfinite(x_km) or not math.isfinite(y_km):
            raise ValueError("Carrier coordinates must be finite")
        col = math.floor(x_km / CARRIER_RESOLUTION_KM)
        row = math.floor(y_km / CARRIER_RESOLUTION_KM)
        ExactSurfaceLookup.carrier_index(row, col)
        return row, col

    def fragment_ids_for_carrier(self, row: int, col: int) -> tuple[int, ...]:
        cell = self.carrier_index(row, col)
        offsets = self._array("cell_offsets")
        start, stop = int(offsets[cell]), int(offsets[cell + 1])
        return tuple(range(start, stop))

    def fragment_ids_for_xy(self, x_km: float, y_km: float) -> tuple[int, ...]:
        return self.fragment_ids_for_carrier(*self.carrier_row_col_for_xy(x_km, y_km))

    def barony_for_fragment(self, fragment_id: int) -> int:
        if not 0 <= fragment_id < EXACT_FRAGMENT_COUNT:
            raise IndexError(f"Fragment ID out of range: {fragment_id}")
        return int(self._barony[fragment_id])

    def barony_ids_for_carrier(self, row: int, col: int) -> tuple[int, ...]:
        fragment_ids = self.fragment_ids_for_carrier(row, col)
        return tuple(sorted({self.barony_for_fragment(i) for i in fragment_ids}))

    def barony_ids_for_xy(self, x_km: float, y_km: float) -> tuple[int, ...]:
        return self.barony_ids_for_carrier(*self.carrier_row_col_for_xy(x_km, y_km))

    def fragment_records_for_carrier(self, row: int, col: int) -> tuple[dict[str, Any], ...]:
        records: list[dict[str, Any]] = []
        fragment_rows = self._array("fragment_row")
        fragment_cols = self._array("fragment_col")
        components = self._array("fragment_component_index")
        areas = self._array("fragment_area_km2")
        flags = self._array("fragment_flags")
        for fragment_id in self.fragment_ids_for_carrier(row, col):
            records.append(
                {
                    "fragment_id": fragment_id,
                    "row": int(fragment_rows[fragment_id]),
                    "col": int(fragment_cols[fragment_id]),
                    "component_index": int(components[fragment_id]),
                    "area_km2": float(areas[fragment_id]),
                    "flags": int(flags[fragment_id]),
                    "barony_id": self.barony_for_fragment(fragment_id),
                }
            )
        return tuple(records)

    def boundary_wkb(self, fragment_id: int) -> bytes | None:
        """Return exact registered boundary WKB, or ``None`` for implicit cells."""

        if not 0 <= fragment_id < EXACT_FRAGMENT_COUNT:
            raise IndexError(f"Fragment ID out of range: {fragment_id}")
        explicit = self._array("explicit_fragment_id")
        position = int(self._np.searchsorted(explicit, fragment_id))
        if position >= explicit.size or int(explicit[position]) != fragment_id:
            return None
        offsets = self._array("boundary_wkb_offsets")
        raw = self._array("boundary_wkb_bytes")
        start, stop = int(offsets[position]), int(offsets[position + 1])
        return bytes(memoryview(raw[start:stop]))

    def close(self) -> None:
        registry = getattr(self, "_registry", None)
        if registry is not None:
            registry.close()
        mmap = getattr(getattr(self, "_barony", None), "_mmap", None)
        if mmap is not None:
            mmap.close()
        self._cache.clear()

    def __enter__(self) -> "ExactSurfaceLookup":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def self_test(*, verify_hashes: bool = False) -> dict[str, Any]:
    """Exercise pure parsers and exact-surface indexing without writing files."""

    # Minimal GeoPackage header with no envelope and a little-endian WKB Point.
    synthetic = b"GP" + bytes((0, 1)) + struct.pack("<i", 99999)
    synthetic += struct.pack("<BI2d", 1, 1, 2.0, 3.0)
    parsed_wkb = gpkg_wkb(synthetic)
    parser_ok = parsed_wkb == struct.pack("<BI2d", 1, 1, 2.0, 3.0)

    with ExactSurfaceLookup() as lookup:
        example_ids = lookup.fragment_ids_for_carrier(38, 1265)
        exact_ok = example_ids == (5, 6)
        example_baronies = lookup.barony_ids_for_carrier(38, 1265)
        explicit_wkb = lookup.boundary_wkb(0)
        boundary_ok = bool(explicit_wkb and explicit_wkb[0] in (0, 1))
        boundary_ok = boundary_ok and lookup.boundary_wkb(17) is None

    report: dict[str, Any] = {
        "ok": parser_ok and exact_ok and boundary_ok,
        "gpkg_wkb_parser_ok": parser_ok,
        "exact_surface_example_ok": exact_ok,
        "exact_boundary_wkb_ok": boundary_ok,
        "carrier_38_1265_fragment_ids": example_ids,
        "carrier_38_1265_barony_ids": example_baronies,
        "source_hashes": None,
    }
    if verify_hashes:
        hash_report = verify_sources()
        report["source_hashes"] = hash_report
        report["ok"] = bool(report["ok"] and hash_report["ok"])
    return report


def _main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-hashes",
        action="store_true",
        help="Hash every active source, including the 839 MB terrain raster.",
    )
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Print JSON source-manifest rows instead of the self-test.",
    )
    args = parser.parse_args(argv)
    if args.manifest:
        print(json.dumps(source_manifest_rows(), ensure_ascii=False, indent=2))
        return 0
    report = self_test(verify_hashes=args.verify_hashes)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
