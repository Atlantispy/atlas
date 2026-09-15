"""Sparse, deterministic 10 m evidence-tile prototype."""

from .engine import (
    CategoricalRecipe,
    ContinuousRecipe,
    EvidenceTile,
    GridSpec,
    ParentRasterWindow,
    PolygonFeature,
    TerrainRecipe,
    TileSpec,
    canonical_hash,
    decode_compact_tile,
    refine_continuous,
    refine_parent_classes,
    refine_parent_probabilities,
    refine_terrain,
    rasterize_exact_vectors,
)

__all__ = [
    "CategoricalRecipe",
    "ContinuousRecipe",
    "EvidenceTile",
    "GridSpec",
    "ParentRasterWindow",
    "PolygonFeature",
    "TerrainRecipe",
    "TileSpec",
    "canonical_hash",
    "decode_compact_tile",
    "refine_continuous",
    "refine_parent_classes",
    "refine_parent_probabilities",
    "refine_terrain",
    "rasterize_exact_vectors",
]
