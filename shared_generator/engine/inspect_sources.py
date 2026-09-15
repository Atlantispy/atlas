from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import rasterio
from shapely.geometry import shape

from source_catalogue import generator_root, source_path

ROOT = generator_root()

PATHS = {
    "terrain": source_path("terrain_d31_100m"),
    "sea": source_path("obsidian_sea_mask_100m"),
    "still_terrain": source_path("stillklinge_terrain_100m"),
    "still_flood": source_path("stillklinge_flood_100m"),
    "moor_core": source_path("moorwandler_core_wetland_100m"),
    "seren_water": source_path("serenakrone_water_100m"),
    "flood_100m": source_path("h22_flood_candidates_100m"),
    "coast": source_path("coastline"),
    "major": source_path("v42_active_major"),
    "minor": source_path("v42_active_minor"),
    "special": source_path("v42_active_special"),
    "still112": source_path("v42_stillklinge_local_112"),
    "flood": source_path("h22_ordinary_floodplains"),
    "moor_transition": source_path("h22_moorwandler_transition"),
    "gpkg": source_path("stage6b_province_gpkg"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    report: dict[str, object] = {}
    for key in ("terrain", "sea", "still_terrain", "still_flood", "moor_core", "seren_water", "flood_100m"):
        path = PATHS[key]
        with rasterio.open(path) as ds:
            sample = ds.read(1, window=((0, min(ds.height, 1000)), (0, min(ds.width, 1000))))
            report[key] = {
                "path": str(path), "sha256": sha256(path), "shape": [ds.height, ds.width],
                "count": ds.count, "dtype": ds.dtypes, "nodata": ds.nodata,
                "transform": list(ds.transform)[:6], "bounds": list(ds.bounds),
                "crs": str(ds.crs), "tags": ds.tags(),
                "sample_min": float(sample.min()), "sample_max": float(sample.max()),
            }
    if "--rasters-only" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return
    for key in ("coast", "major", "minor", "special", "still112", "flood", "moor_transition"):
        path = PATHS[key]
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features", [])
        geometries = [shape(item["geometry"]) for item in features]
        columns = sorted({key for item in features for key in item.get("properties", {})})
        bounds = [
            min(g.bounds[0] for g in geometries), min(g.bounds[1] for g in geometries),
            max(g.bounds[2] for g in geometries), max(g.bounds[3] for g in geometries),
        ] if geometries else []
        geom_counts: dict[str, int] = {}
        for geom in geometries:
            geom_counts[geom.geom_type] = geom_counts.get(geom.geom_type, 0) + 1
        report[key] = {
            "path": str(path), "sha256": sha256(path), "count": len(features),
            "crs": payload.get("crs"), "columns": columns,
            "geom_types": geom_counts, "bounds": bounds,
            "first_rows": [item.get("properties", {}) for item in features[:3]],
        }
    with sqlite3.connect(PATHS["gpkg"]) as conn:
        report["gpkg"] = {
            "path": str(PATHS["gpkg"]), "sha256": sha256(PATHS["gpkg"]),
            "contents": [dict(zip(("table_name", "data_type", "identifier", "srs_id"), row)) for row in conn.execute(
                "SELECT table_name,data_type,identifier,srs_id FROM gpkg_contents ORDER BY table_name"
            )],
            "geometry_columns": [dict(zip(("table_name", "column_name", "geometry_type", "srs_id"), row)) for row in conn.execute(
                "SELECT table_name,column_name,geometry_type_name,srs_id FROM gpkg_geometry_columns ORDER BY table_name"
            )],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
