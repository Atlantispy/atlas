"""Explicit Step 8 source stages after the established compact owner stages.

This does not freeze a WP9 runtime, migrate a store or start an interval.
Callers retain their authenticated predecessor source manifest. Initial
partitions take compact_scope, meshes take compact_context, and spatial
bounds/graphs/transport use LIVE.construction with the caller's existing scope.
"""
from hashlib import sha256

import live_finite_patch as FINITE
import live_collar_patch as COLLAR
import live_mesh_patch as MESH
import live_partition_patch as PARTITION
import live_spatial_patch as SPATIAL
import spatial_validation_patch as VALIDATION


STAGES = (
    ('integration_differential_geometry.py', 'partition-construction', PARTITION.transform),
    ('integration_differential_geometry.py', 'differential-working-records', SPATIAL.differential_source),
    ('integration_exterior_mesh.py', 'ordinary-mesh-construction', MESH.transform_exterior),
    ('integration_differential_mesh.py', 'differential-mesh-construction', MESH.transform_differential),
    ('integration_spatial_ale.py', 'spatial-graph-construction', SPATIAL.ale_source),
    ('integration_spatial_transport.py', 'spatial-transport-working-records', SPATIAL.transport_source),
    ('integration_spatial_owner.py', 'spatial-owner-lifetimes', SPATIAL.owner_source),
    ('integration_spatial_reservoir.py', 'finite-proposal-working-records', FINITE.reservoir_source),
    ('integration_dual_geometry.py', 'dual-geometry-working-records', FINITE.dual_source),
    ('regional_collar3d.py', 'collar-bounded-adoption', COLLAR.collar_source),
    # Step 8: a compact transport result reaches the owner's dual-measure
    # audit as a record reference; the existing bounded-access seam reads it.
    ('integration_dual_measures.py', 'dual-measure-transport-audit', VALIDATION.measures_source),
)


def apply_native(sources):
    """Apply once to an explicit selected source map; preserve all other files."""
    if type(sources) is not dict or any(type(value) is not str for value in sources.values()):
        raise ValueError('explicit native source text inventory required')
    if not {name for name, _, _ in STAGES} <= sources.keys():
        raise ValueError('complete Step 8 native owner source inventory required')
    result, stages = dict(sources), []
    for name, label, transform in STAGES:
        before = result[name]
        after = transform(before)
        compile(after, name, 'exec')
        result[name] = after
        stages.append(dict(module=name, stage=label,
            input_sha256=sha256(before.encode()).hexdigest(),
            output_sha256=sha256(after.encode()).hexdigest()))
    return result, dict(schema='atlas.live-memory-source-stages.v1', stages=stages,
        frozen_wp9=False, migration=False, interval_advance=False)
