"""Adapters connecting fingerprints to manifests, lineage and future cache keys."""

from __future__ import annotations

from typing import Any, Iterable, Mapping
import re

from .canonical import SemanticFingerprint, semantic_fingerprint
from .ids import StructuredId


TRANSPORT_ONLY_FIELDS = frozenset(
    {
        "absolute_path",
        "archive_format",
        "codec",
        "compression",
        "compression_level",
        "created_at",
        "created_utc",
        "file_path",
        "last_write_utc",
        "modified_time",
        "path",
        "remote_path",
        "timestamp",
        "workspace_path",
    }
)

_PATH_FIELDS = frozenset({"absolute_path", "file_path", "path", "remote_path", "workspace_path"})
_LOGICAL_ID_FIELDS = ("logical_id", "source_id", "artifact_id", "feature_id", "content_id", "id")
_CONTENT_ID_FIELDS = ("semantic_fingerprint", "content_fingerprint", "sha256")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ROLE_COLLECTIONS = frozenset({"inputs", "parents", "sources"})


def _validate_transport_projection(value: Any, parent_key: str | None = None, path: str = "$") -> None:
    """Fail closed before a transport path is removed from semantic identity."""

    if isinstance(value, Mapping):
        omitted_paths = [field for field in _PATH_FIELDS if field in value and value[field] is not None]
        if omitted_paths:
            logical_fields = [field for field in _LOGICAL_ID_FIELDS if isinstance(value.get(field), str) and value[field]]
            content_fields = [field for field in _CONTENT_ID_FIELDS if isinstance(value.get(field), str) and value[field]]
            if not logical_fields:
                raise ValueError(f"{path}: transport path omission requires a stable logical ID")
            if not content_fields:
                raise ValueError(f"{path}: transport path omission requires a semantic content fingerprint")
            content = value[content_fields[0]]
            if content.startswith("dgh:"):
                SemanticFingerprint.parse(content)
            elif not _HEX_64.fullmatch(content):
                raise ValueError(f"{path}: content fingerprint must be a dgh fingerprint or lowercase SHA-256")
            if parent_key in _ROLE_COLLECTIONS and not (isinstance(value.get("role"), str) and value["role"]):
                raise ValueError(f"{path}: {parent_key} record must retain an explicit semantic role")
        for key, child in value.items():
            _validate_transport_projection(child, key, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_transport_projection(child, parent_key, f"{path}[{index}]")


def fingerprint_manifest(manifest: Mapping[str, Any]) -> SemanticFingerprint:
    """Fingerprint a manifest while excluding declared transport metadata."""

    _validate_transport_projection(manifest)
    return semantic_fingerprint(
        "manifest",
        manifest,
        omit_fields=TRANSPORT_ONLY_FIELDS,
        unordered_record_lists={"artifacts", "entries", "files", "inputs", "sources"},
    )


def fingerprint_lineage(lineage: Mapping[str, Any]) -> SemanticFingerprint:
    """Fingerprint derivation lineage independently of storage location/codec."""

    _validate_transport_projection(lineage)
    return semantic_fingerprint(
        "lineage",
        lineage,
        omit_fields=TRANSPORT_ONLY_FIELDS,
        unordered_record_lists={"parents", "sources", "inputs"},
    )


def future_cache_key(
    *,
    recipe_fingerprint: str,
    input_fingerprints: Iterable[str],
    parameters: Mapping[str, Any],
    spatial_unit_id: str,
    code_version: str,
    schema_version: str,
) -> SemanticFingerprint:
    """Create a future cache key from exact semantic dependencies only."""

    StructuredId.decode(spatial_unit_id)
    recipe = SemanticFingerprint.parse(recipe_fingerprint)
    inputs = sorted(str(SemanticFingerprint.parse(value)) for value in input_fingerprints)
    material = {
        "code_version": code_version,
        "input_fingerprints": inputs,
        "parameters": dict(parameters),
        "recipe_fingerprint": str(recipe),
        "schema_version": schema_version,
        "spatial_unit_id": spatial_unit_id,
    }
    return semantic_fingerprint("cache-key", material)
