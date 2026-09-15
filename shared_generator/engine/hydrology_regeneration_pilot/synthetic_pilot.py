"""Deterministic parent-conserving evidence tile for the isolated pilot."""

from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path

import numpy as np

from hydrology_regeneration import (
    InMemoryTileStore,
    RegenerationConfig,
    TileMetadata,
    TopologyConstraint,
    corridor_mask_from_axis,
    regenerate_tile_route,
    save_result,
    _box_mean,
)


UNITS = {
    "elevation_m": "m",
    "broad_gradient_row": "m/m",
    "broad_gradient_col": "m/m",
    "local_gradient_row": "m/m",
    "local_gradient_col": "m/m",
    "runoff_mm_y": "mm/y",
}


def build_synthetic_evidence(
    shape: tuple[int, int] = (120, 120), valley_amplitude: float = 6.0
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Make a sinuous runoff-supported valley inside a straight old corridor.

    The returned 100 m parent is exactly the 10x10 block mean of the modelled
    10 m surface.  It is evidence for parent conservation, not an independent
    claim of surveyed 10 m topography.
    """
    rows, cols = np.indices(shape, dtype=np.float32)
    phase = 2.0 * np.pi * (cols - 5.0) / 109.0
    valley_row = 60.0 + valley_amplitude * np.sin(phase)
    cross_valley = rows - valley_row
    microrelief = 0.11 * np.sin(rows / 4.7 + cols / 8.3) + 0.06 * np.sin(rows / 9.1 - cols / 5.9)
    elevation = 520.0 - 0.74 * cols + 0.24 * cross_valley**2 + microrelief
    elevation = elevation.astype(np.float32)
    parent = elevation.reshape(shape[0] // 10, 10, shape[1] // 10, 10).mean(axis=(1, 3)).astype(np.float32)

    broad_surface = _box_mean(elevation, radius=6)
    broad_row, broad_col = np.gradient(broad_surface.astype(np.float64), 10.0)
    local_row, local_col = np.gradient(elevation.astype(np.float64), 10.0)
    # Deliberately wet stress window so the 1.2 km synthetic tile spans a
    # measurable tier-2 width envelope without inventing upstream inflow.
    runoff = 2350.0 + 420.0 * np.sin(cols / 21.0) + 180.0 * np.cos(rows / 31.0)
    runoff = np.maximum(runoff, 700.0).astype(np.float32)
    return {
        "elevation_m": elevation,
        "broad_gradient_row": broad_row.astype(np.float32),
        "broad_gradient_col": broad_col.astype(np.float32),
        "local_gradient_row": local_row.astype(np.float32),
        "local_gradient_col": local_col.astype(np.float32),
        "runoff_mm_y": runoff,
    }, parent


def make_tile_references(
    arrays: dict[str, np.ndarray], store: InMemoryTileStore
) -> dict[str, object]:
    references: dict[str, object] = {}
    for name, array in arrays.items():
        metadata = TileMetadata(
            tile_id="SYNTHETIC-TIER2-VALLEY-001",
            field_name=name,
            shape=array.shape,
            dtype="float32",
            units=UNITS[name],
        )
        if name == "runoff_mm_y":
            # Demonstrate sparse residual-patch consumption.  The base omits a
            # compact rainfall anomaly; the final field is recovered by patch.
            base = array.copy()
            indices = np.flatnonzero(np.indices(array.shape)[1].ravel() == 75)
            residual = np.full(indices.shape, 12.5, dtype=np.float32)
            base.ravel()[indices] -= residual
            base_ref = store.put_full(base, metadata)
            references[name] = store.put_patch(base_ref, indices, residual)
        else:
            full = store.put_full(array, metadata)
            references[name] = store.put_ref(full) if name == "broad_gradient_row" else full
    return references


def run_synthetic_pilot(output_directory: Path | None = None, valley_amplitude: float = 6.0):
    arrays, parent = build_synthetic_evidence(valley_amplitude=valley_amplitude)
    store = InMemoryTileStore()
    references = make_tile_references(arrays, store)
    inherited_axis = [(60, 5), (60, 60), (60, 114)]
    config = RegenerationConfig(route_class="tier2", persistence="perennial")
    corridor = corridor_mask_from_axis(
        arrays["elevation_m"].shape,
        inherited_axis,
        buffer_cells=int(round(config.search_buffer_m / config.cell_size_m)),
    )
    topology = TopologyConstraint(
        source=(60, 5),
        ordered_contacts=((60, 60),),
        receiver=(60, 114),
        contact_ids=("SYNTHETIC-CONFLUENCE-01",),
    )
    result = regenerate_tile_route(
        references,
        store,
        parent,
        corridor,
        inherited_axis,
        topology,
        config,
    )
    if output_directory is not None:
        output_directory.mkdir(parents=True, exist_ok=True)
        save_result(output_directory / "synthetic_regeneration_report.json", result)
        # Diadem's local raster uses positive-south Y: row increases with +Y;
        # map north is decreasing Y.  Do not apply north-up sign inversion.
        coords = [[float(col * 10 + 5), float(row * 10 + 5)] for row, col in result.path_cells]
        feature = {
            "type": "FeatureCollection",
            "name": "synthetic_regenerated_route_review_only",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "status": "WORKING PROPOSAL - REVIEW ONLY - NOT CANON",
                        "route_class": config.route_class,
                        "cell_size_m": 10,
                        "model_resolution_m": 10,
                        "physical_source_resolution_m": 100,
                        "effective_evidence_resolution_m": 100,
                        "axis_convention": "X increases east; Y/row increases south; map north is decreasing Y",
                        "anti_smoothing_pass": result.metrics["anti_smoothing_pass"],
                    },
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            ],
        }
        (output_directory / "synthetic_regenerated_route.geojson").write_text(
            json.dumps(feature, indent=2), encoding="utf-8"
        )
        summary = {
            "config": asdict(config),
            "result_files": ["synthetic_regeneration_report.json", "synthetic_regenerated_route.geojson"],
            "metrics": result.metrics,
        }
        (output_directory / "pilot_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return result, arrays, parent, references, store, corridor, inherited_axis, topology, config


if __name__ == "__main__":
    run_synthetic_pilot(Path(__file__).resolve().parent / "pilot_output")
