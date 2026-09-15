"""Diadem Phase-1 identity and whole-engine acceptance contracts."""

from .adapters import fingerprint_lineage, fingerprint_manifest, future_cache_key
from .canonical import (
    CANONICALIZATION_VERSION,
    CanonicalizationError,
    SemanticFingerprint,
    binary_fingerprint,
    canonical_json_bytes,
    semantic_fingerprint,
)
from .ids import (
    StructuredId,
    feature_id,
    layer_id,
    resolution_id,
    run_id,
    tile_id,
)

__all__ = [
    "CANONICALIZATION_VERSION",
    "CanonicalizationError",
    "SemanticFingerprint",
    "StructuredId",
    "binary_fingerprint",
    "canonical_json_bytes",
    "feature_id",
    "fingerprint_lineage",
    "fingerprint_manifest",
    "future_cache_key",
    "layer_id",
    "resolution_id",
    "run_id",
    "semantic_fingerprint",
    "tile_id",
]
