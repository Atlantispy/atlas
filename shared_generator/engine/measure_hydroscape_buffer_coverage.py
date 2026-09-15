"""Read-only measurement of buffered active hydroscape against exact surface."""

from __future__ import annotations

import json
import time
from collections import Counter

import numpy as np
from affine import Affine
from rasterio.features import shapes
from shapely import from_wkb, union_all
from shapely.geometry import shape

from stage6c_source_stack import (
    CARRIER_SHAPE,
    EXACT_FRAGMENT_COUNT,
    EXACT_SURFACE_REGISTRY,
    H22_ACTIVE_L1_LAKES,
    H22_ACTIVE_LEGACY_C1_LAKES,
    H22_ACTIVE_LEGACY_CONNECTORS,
    V42_ACTIVE_MAJOR,
    V42_ACTIVE_MINOR,
    V42_ACTIVE_SPECIAL,
    read_geojson_geometries,
)


def build_exact_surface_parts() -> tuple[object, object, float, dict[str, float | int]]:
    """Return unions of implicit full cells and explicit exact fragments."""

    with np.load(EXACT_SURFACE_REGISTRY, allow_pickle=False) as registry:
        explicit_ids = registry["explicit_fragment_id"]
        fragment_rows = registry["fragment_row"]
        fragment_cols = registry["fragment_col"]
        fragment_areas = registry["fragment_area_km2"]

        is_implicit = np.ones(EXACT_FRAGMENT_COUNT, dtype=bool)
        is_implicit[explicit_ids] = False
        if not np.all(fragment_areas[is_implicit] == 1.0):
            raise RuntimeError("A supposedly implicit fragment is not a full 1 km cell")

        implicit_mask = np.zeros(CARRIER_SHAPE, dtype=np.uint8)
        implicit_mask[fragment_rows[is_implicit], fragment_cols[is_implicit]] = 1
        implicit_regions = [
            shape(geometry)
            for geometry, value in shapes(
                implicit_mask,
                mask=implicit_mask.astype(bool),
                connectivity=4,
                transform=Affine(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            )
            if value == 1
        ]
        implicit_union = union_all(implicit_regions)

        offsets = registry["boundary_wkb_offsets"]
        raw = registry["boundary_wkb_bytes"]
        explicit_wkb = [
            bytes(raw[int(offsets[i]) : int(offsets[i + 1])])
            for i in range(explicit_ids.size)
        ]
        explicit_union = union_all(from_wkb(explicit_wkb))
        exact_area = float(fragment_areas.sum())

    measured_area = float(implicit_union.area + explicit_union.area)
    if abs(measured_area - exact_area) > 1e-6:
        raise RuntimeError(
            f"Exact surface reconstruction area mismatch: {measured_area} != {exact_area}"
        )
    details = {
        "exact_fragment_count": EXACT_FRAGMENT_COUNT,
        "implicit_full_cell_count": int(is_implicit.sum()),
        "explicit_fragment_count": int(explicit_ids.size),
        "implicit_region_count": len(implicit_regions),
        "exact_surface_area_km2": exact_area,
        "reconstructed_surface_area_km2": measured_area,
    }
    return implicit_union, explicit_union, exact_area, details


def read_active_hydroscape() -> tuple[object, dict[str, int]]:
    source_paths = {
        "v42_major": V42_ACTIVE_MAJOR,
        "v42_minor": V42_ACTIVE_MINOR,
        "v42_special": V42_ACTIVE_SPECIAL,
        "active_l1_lakes": H22_ACTIVE_L1_LAKES,
        "active_legacy_c1_lakes": H22_ACTIVE_LEGACY_C1_LAKES,
        "active_legacy_connectors": H22_ACTIVE_LEGACY_CONNECTORS,
    }
    geometries = []
    counts: dict[str, int] = {}
    for key, path in source_paths.items():
        rows = [shape(raw) for raw in read_geojson_geometries(path)]
        counts[key] = len(rows)
        geometries.extend(rows)
    return union_all(geometries), counts


def read_features(path: object) -> list[tuple[object, dict[str, object]]]:
    return [
        (shape(raw), properties)
        for raw, properties in read_geojson_geometries(path, include_properties=True)
    ]


def exact_surface_coverage(
    corridor: object, implicit_surface: object, explicit_surface: object
) -> float:
    return float(
        corridor.intersection(implicit_surface).area
        + corridor.intersection(explicit_surface).area
    )


def ten_metre_burden(area_km2: float) -> dict[str, float | int]:
    cells = int(round(area_km2 * 10_000.0))
    gib = 1024.0**3
    return {
        "approx_10m_cells": cells,
        "uint8_mask_gib": cells / gib,
        "one_float32_band_gib": cells * 4.0 / gib,
        "six_float32_bands_gib": cells * 24.0 / gib,
        "eight_float32_bands_gib": cells * 32.0 / gib,
    }


def build_adaptive_corridors() -> tuple[object, object, dict[str, object]]:
    """Build conservative full-water and sparse-shoreline adaptive alternatives."""

    major_rows = read_features(V42_ACTIVE_MAJOR)
    minor_rows = read_features(V42_ACTIVE_MINOR)
    special_rows = read_features(V42_ACTIVE_SPECIAL)
    l1_rows = read_features(H22_ACTIVE_L1_LAKES)
    legacy_lake_rows = read_features(H22_ACTIVE_LEGACY_C1_LAKES)
    connector_rows = read_features(H22_ACTIVE_LEGACY_CONNECTORS)

    regional = [row for row in minor_rows if int(row[1].get("tier_code", 0)) == 2]
    local = [row for row in minor_rows if int(row[1].get("tier_code", 0)) == 1]
    if len(regional) + len(local) != len(minor_rows):
        raise RuntimeError("Minor tier_code does not classify the full active network")

    titan_major = [row for row in major_rows if row[1].get("system") == "Titan"]
    other_major = [row for row in major_rows if row[1].get("system") != "Titan"]
    major_corridor = union_all(
        [
            union_all([row[0] for row in other_major]).buffer(0.2, quad_segs=8),
            union_all([row[0] for row in titan_major]).buffer(0.4, quad_segs=8),
        ]
    )
    regional_corridor = union_all([row[0] for row in regional]).buffer(0.1, quad_segs=8)
    local_corridor = union_all([row[0] for row in local]).buffer(0.05, quad_segs=8)

    water_polygons = [row[0] for row in l1_rows + legacy_lake_rows]
    special_polygons = [row[0] for row in special_rows if "Polygon" in row[0].geom_type]
    special_linear = [
        row[0]
        for row in special_rows
        if row[0].geom_type in {"LineString", "MultiLineString", "Point", "MultiPoint"}
    ]
    connector_geometries = [row[0] for row in connector_rows]

    water_union = union_all(water_polygons + special_polygons)
    auxiliary_corridor = union_all(special_linear + connector_geometries).buffer(
        0.05, quad_segs=8
    )
    river_corridor = union_all([major_corridor, regional_corridor, local_corridor])

    # Conservative: include complete permanent-water/special footprints plus a
    # 100 m exterior margin. Sparse: refine only a 100 m shoreline band; interiors
    # remain at parent resolution unless a later bathymetry task activates them.
    full_water_corridor = union_all(
        [river_corridor, water_union.buffer(0.1, quad_segs=8), auxiliary_corridor]
    )
    shoreline_corridor = union_all(
        [river_corridor, water_union.boundary.buffer(0.1, quad_segs=8), auxiliary_corridor]
    )

    def class_summary(rows: list[tuple[object, dict[str, object]]]) -> dict[str, object]:
        return {
            "feature_count": len(rows),
            "total_axis_length_km": float(sum(row[0].length for row in rows)),
            "strahler_order": dict(
                sorted(Counter(str(row[1].get("strahler_order")) for row in rows).items())
            ),
            "persistence_preclassification": dict(
                sorted(
                    Counter(
                        str(row[1].get("persistence_preclassification")) for row in rows
                    ).items()
                )
            ),
            "unresolved_persistence_count": sum(
                row[1].get("persistence_authority")
                == "UNRESOLVED_AFTER_STILLKLINGE_SUPERSESSION"
                for row in rows
            ),
        }

    summary: dict[str, object] = {
        "rule": {
            "active_major_each_side_m": 200,
            "titan_major_each_side_m": 400,
            "minor_tier_2_regional_tributary_each_side_m": 100,
            "minor_tier_1_local_stream_each_side_m": 50,
            "lake_and_special_polygon_margin_m": 100,
            "legacy_connector_and_special_line_or_point_radius_m": 50,
            "channel_width_attribute_present": False,
            "minor_classification": (
                "Recorded tier_code is complete for all 3,177 features; Strahler order, "
                "catchment and persistence are retained as audit/reliability evidence."
            ),
        },
        "major": {
            "feature_count": len(major_rows),
            "total_axis_length_km": float(sum(row[0].length for row in major_rows)),
            "titan_feature_count": len(titan_major),
            "titan_axis_length_km": float(sum(row[0].length for row in titan_major)),
            "other_major_feature_count": len(other_major),
        },
        "regional_tributary": class_summary(regional),
        "local_stream": class_summary(local),
        "water_polygon_count": len(water_polygons),
        "special_polygon_count": len(special_polygons),
        "special_line_or_point_count": len(special_linear),
        "legacy_connector_count": len(connector_geometries),
        "water_and_special_polygon_area_km2": float(water_union.area),
        "river_corridor_unclipped_area_km2": float(river_corridor.area),
        "full_water_corridor_unclipped_area_km2": float(full_water_corridor.area),
        "shoreline_corridor_unclipped_area_km2": float(shoreline_corridor.area),
    }
    return full_water_corridor, shoreline_corridor, summary


def main() -> None:
    started = time.perf_counter()
    implicit, explicit, surface_area, surface_details = build_exact_surface_parts()
    surface_seconds = time.perf_counter() - started

    hydrology_started = time.perf_counter()
    hydroscape, source_counts = read_active_hydroscape()
    hydrology_seconds = time.perf_counter() - hydrology_started

    results = []
    for distance in (0.5, 1.0, 2.0):
        buffer_started = time.perf_counter()
        corridor = hydroscape.buffer(distance, quad_segs=8)
        covered_area = float(
            corridor.intersection(implicit).area + corridor.intersection(explicit).area
        )
        results.append(
            {
                "buffer_km": distance,
                "surface_covered_km2": covered_area,
                "surface_covered_percent": 100.0 * covered_area / surface_area,
                "unclipped_corridor_km2": float(corridor.area),
                "ten_metre_burden": ten_metre_burden(covered_area),
                "seconds": time.perf_counter() - buffer_started,
            }
        )

    adaptive_started = time.perf_counter()
    adaptive_full_water, adaptive_shoreline, adaptive_summary = build_adaptive_corridors()
    full_water_area = exact_surface_coverage(adaptive_full_water, implicit, explicit)
    shoreline_area = exact_surface_coverage(adaptive_shoreline, implicit, explicit)
    adaptive_results = {
        "full_water_footprints_plus_margin": {
            "surface_covered_km2": full_water_area,
            "surface_covered_percent": 100.0 * full_water_area / surface_area,
            "ten_metre_burden": ten_metre_burden(full_water_area),
        },
        "shoreline_bands_parent_resolution_water_interiors": {
            "surface_covered_km2": shoreline_area,
            "surface_covered_percent": 100.0 * shoreline_area / surface_area,
            "ten_metre_burden": ten_metre_burden(shoreline_area),
        },
        "classification": adaptive_summary,
        "seconds": time.perf_counter() - adaptive_started,
    }

    report = {
        "method": (
            "Exact surface = 2,480,056 implicit 1km squares plus 14,857 exact "
            "registered boundary fragments. Active hydroscape = V4.2 major, minor, "
            "special plus 486 active L1 lakes, 11 retained C1 lakes and their 11 "
            "connectors. Seasonal basins excluded. Euclidean round buffers; unioned "
            "before exact-surface intersection."
        ),
        "surface": surface_details,
        "source_feature_counts": source_counts,
        "hydroscape_geometry_type": hydroscape.geom_type,
        "surface_build_seconds": surface_seconds,
        "hydroscape_union_seconds": hydrology_seconds,
        "coverage": results,
        "adaptive_10m_corridors": adaptive_results,
        "full_surface_10m_burden": ten_metre_burden(surface_area),
        "total_seconds": time.perf_counter() - started,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
