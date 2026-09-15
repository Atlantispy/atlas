"""Fail-closed Stage 6C access to the editable 100 m terrain authority.

The Zarr authority is mutable across committed generations, so it is not a
member of the immutable 29-file source catalogue.  Its identity is instead the
signed authority manifest triple ``(authority_id, generation, root_hash)``.
The two TIFFs from which generation zero was composed remain hash-locked
lineage evidence only; this module never opens either TIFF for terrain reads.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from source_catalogue import generator_root, source_entry
from zarr_authority import AuthorityError, AuthorityReadSession


DEFAULT_AUTHORITY_RELATIVE_PATH = Path(
    "working_authorities/effective_terrain_100m"
)
EXPECTED_SHAPE = (18_600, 22_000)
EXPECTED_DTYPE = "float32"
EXPECTED_TRANSFORM = (0.1, 0.0, 0.0, 0.0, 0.1, 0.0)
SEALED_TERRAIN_LINEAGE_KEYS = (
    "terrain_d31_100m",
    "stillklinge_terrain_100m",
)


def authority_root(*, require_exists: bool = True) -> Path:
    """Resolve the one portable production authority root.

    Tests that need another store pass ``root=`` directly to the reader or
    verifier. Environment state can never redirect a production generator run.
    """

    path = (generator_root() / DEFAULT_AUTHORITY_RELATIVE_PATH).absolute()
    if require_exists and not path.is_dir():
        raise AuthorityError(f"Terrain authority root is missing: {path}")
    return path


def expected_sealed_tiff_lineage() -> dict[str, dict[str, Any]]:
    """Return the exact catalogue identity of the sealed generation-0 TIFFs."""

    result: dict[str, dict[str, Any]] = {}
    for key in SEALED_TERRAIN_LINEAGE_KEYS:
        entry = source_entry(key)
        result[key] = {
            "relative_path": str(entry["relative_path"]).replace("\\", "/"),
            "sha256": str(entry["sha256"]),
            "size_bytes": int(entry["bytes"]),
        }
    return result


def _normalise_lineage_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "relative_path": str(record.get("relative_path", "")).replace("\\", "/"),
        "sha256": str(record.get("sha256", "")),
        "size_bytes": int(record.get("size_bytes", 0)),
    }


def _array_attributes(array: Any) -> dict[str, Any]:
    attrs = array.attrs
    if hasattr(attrs, "asdict"):
        return dict(attrs.asdict())
    return dict(attrs)


def descriptor_from_open_session(session: AuthorityReadSession) -> dict[str, Any]:
    """Validate runtime semantics and return the fingerprintable identity."""

    manifest = session.manifest
    array = session.array
    if not isinstance(manifest, dict) or array is None:
        raise AuthorityError("Terrain authority read session is not open")
    if manifest.get("authority_role") != "EDITABLE_WORKING_AUTHORITY":
        raise AuthorityError("Terrain store is not the editable working authority")
    authority_id = str(manifest.get("authority_id", ""))
    root_hash = str(manifest.get("root_hash", ""))
    generation = manifest.get("generation")
    if not authority_id:
        raise AuthorityError("Terrain authority ID is missing")
    if not isinstance(generation, int) or generation < 0:
        raise AuthorityError("Terrain authority generation is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", root_hash):
        raise AuthorityError("Terrain authority root hash is invalid")
    if tuple(map(int, array.shape)) != EXPECTED_SHAPE:
        raise AuthorityError(f"Terrain authority shape is not {EXPECTED_SHAPE}")
    if np.dtype(array.dtype) != np.dtype(EXPECTED_DTYPE):
        raise AuthorityError(f"Terrain authority dtype is not {EXPECTED_DTYPE}")

    attrs = _array_attributes(array)
    transform = tuple(map(float, attrs.get("transform", ())))
    if transform != EXPECTED_TRANSFORM:
        raise AuthorityError(f"Terrain authority transform is not {EXPECTED_TRANSFORM}")
    if attrs.get("schema") != "diadem.editable-terrain-zarr-authority.v1":
        raise AuthorityError("Terrain authority array schema is not active/editable")
    if attrs.get("active_generator_integration") is not True:
        raise AuthorityError("Terrain authority is not enabled for generator integration")

    source_lineage = manifest.get("source_lineage") or {}
    observed_raw = source_lineage.get("sealed_tiff_parents") or {}
    if not isinstance(observed_raw, dict):
        raise AuthorityError("Terrain authority sealed TIFF lineage is malformed")
    if set(observed_raw) != set(SEALED_TERRAIN_LINEAGE_KEYS):
        raise AuthorityError("Terrain authority sealed TIFF lineage key set changed")
    expected = expected_sealed_tiff_lineage()
    observed = {
        key: _normalise_lineage_record(observed_raw.get(key) or {})
        for key in SEALED_TERRAIN_LINEAGE_KEYS
    }
    if observed != expected:
        raise AuthorityError(
            "Terrain authority is not descended from the two hash-locked TIFF parents"
        )

    source_grids = attrs.get("source_grids")
    if not isinstance(source_grids, dict) or set(source_grids) != set(expected):
        raise AuthorityError("Terrain authority source-grid provenance is incomplete")
    for key, expected_record in expected.items():
        grid = source_grids.get(key)
        if (
            not isinstance(grid, dict)
            or grid.get("path") != expected_record["relative_path"]
        ):
            raise AuthorityError(
                f"Terrain authority contains non-portable source-grid provenance: {key}"
            )
    base_semantic = attrs.get("base_semantic_metadata")
    if (
        not isinstance(base_semantic, dict)
        or base_semantic.get("path")
        != expected["terrain_d31_100m"]["relative_path"]
    ):
        raise AuthorityError("Terrain authority base provenance is not portable")
    if attrs.get("source_provenance_path_policy") != (
        "PORTABLE_GENERATOR_ROOT_RELATIVE_SEALED_LINEAGE_REFERENCES"
    ):
        raise AuthorityError("Terrain authority provenance path policy is missing")

    return {
        "authority_id": authority_id,
        "generation": generation,
        "root_hash": root_hash,
        "metadata_sha256": str(manifest.get("metadata_sha256", "")),
        "sealed_tiff_lineage": expected,
    }


def verify_authority(root: Path | None = None) -> dict[str, Any]:
    """Open through the production lock/integrity gate and return its identity."""

    with AuthorityReadSession(root or authority_root()) as session:
        return descriptor_from_open_session(session)


def identity_component(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical subset included in every Stage 6C input fingerprint."""

    return {
        "authority_id": str(descriptor["authority_id"]),
        "generation": int(descriptor["generation"]),
        "root_hash": str(descriptor["root_hash"]),
        "sealed_tiff_lineage": descriptor["sealed_tiff_lineage"],
    }


class TerrainAuthorityReader:
    """One-generation, exclusively locked terrain reader for an analysis run."""

    def __init__(
        self,
        expected_descriptor: Mapping[str, Any],
        *,
        root: Path | None = None,
    ) -> None:
        self.expected = identity_component(expected_descriptor)
        self.root = root or authority_root()
        self.session: AuthorityReadSession | None = None
        self.descriptor: dict[str, Any] | None = None
        self.array: Any = None

    def open(self) -> "TerrainAuthorityReader":
        if self.session is not None:
            raise AuthorityError("Terrain authority reader is already open")
        session = AuthorityReadSession(self.root)
        session.__enter__()
        try:
            descriptor = descriptor_from_open_session(session)
            if identity_component(descriptor) != self.expected:
                raise AuthorityError(
                    "Terrain authority changed after source verification; restart the run"
                )
            self.session = session
            self.descriptor = descriptor
            self.array = session.array
            return self
        except Exception:
            session.__exit__(*__import__("sys").exc_info())
            raise

    def read_block(self, row0: int, col0: int, height: int, width: int) -> np.ndarray:
        if self.array is None:
            raise AuthorityError("Terrain authority reader is not open")
        row1 = row0 + height
        col1 = col0 + width
        if not (0 <= row0 < row1 <= EXPECTED_SHAPE[0]):
            raise AuthorityError("Terrain read rows are outside the authority")
        if not (0 <= col0 < col1 <= EXPECTED_SHAPE[1]):
            raise AuthorityError("Terrain read columns are outside the authority")
        # The per-chunk CRC codec also fails closed if accessed encoded data is
        # corrupt despite having the same byte size as the manifest record.
        return np.asarray(
            self.array[row0:row1, col0:col1], dtype=np.float32
        )

    def close(self) -> None:
        self.array = None
        self.descriptor = None
        if self.session is not None:
            self.session.__exit__(None, None, None)
            self.session = None


__all__ = [
    "DEFAULT_AUTHORITY_RELATIVE_PATH",
    "SEALED_TERRAIN_LINEAGE_KEYS",
    "TerrainAuthorityReader",
    "authority_root",
    "descriptor_from_open_session",
    "expected_sealed_tiff_lineage",
    "identity_component",
    "verify_authority",
]
