#!/usr/bin/env python3
"""Render natural, provenance-safe capital-site maps from Stage 6C.5R V7.

The validated Zarr/SQLite products and their diagnostic review maps are opened
read-only.  This renderer creates a separate cartographic product: terrain is
display-interpolated from the active 100 m authority, accepted major waterways
use their original registered vectors, and grid-derived minor vectors receive
bounded topology-locked display smoothing only.  Nothing produced here is fed
back into the analytical model.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable, Mapping, Sequence


ENGINE_DIR = Path(__file__).resolve().parent
for dependency_directory in (ENGINE_DIR / "zarr_deps", ENGINE_DIR / "generator_deps"):
    value = str(dependency_directory)
    if value not in sys.path:
        sys.path.insert(0, value)

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from rasterio.enums import Resampling
import rasterio
import shapely
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, box
import zarr

import build_stage6c_100m as s6c
from source_catalogue import source_path


METHOD = "STAGE6C5R_NATURAL_CAPITAL_CARTOGRAPHY_V1"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
DATE = "2026-08-30"
SOURCE_DIR = (
    s6c.ROOT
    / "generated_outputs/S6C5R_PHYSICAL_10M_REPAIRED_V7_WORKING_2026-08-30"
)
SOURCE_DB = SOURCE_DIR / "Diadem_Stage6C5R_Physical_Context_WORKING_2026-08-30.sqlite"
SOURCE_ZARR = SOURCE_DIR / "physical_context_10m.zarr"
DEFAULT_OUTPUT_DIR = (
    s6c.ROOT
    / "generated_outputs/S6C5R_CAPITAL_LOCATION_MAPS_NATURAL_V1_WORKING_2026-08-30"
)

MAP_PX = 1400
OVERSAMPLE = 2
WORK_PX = MAP_PX * OVERSAMPLE
CANVAS_W = 1540
CANVAS_H = 1840
MAP_LEFT = 70
MAP_TOP = 185
FINE_CELLS = 300
FINE_CELL_KM = 0.01
MINOR_MAX_DISPLACEMENT_KM = 0.05
MINOR_SUBCELL_CURVATURE_AMPLITUDE_KM = 0.025
MINOR_TERRAIN_GUIDED_OFFSET_KM = 0.047
MINIMUM_CLOSED_CONTOUR_PERIMETER_KM = 2.20
MINIMUM_CLOSED_CONTOUR_AREA_KM2 = 0.12
TERRAIN_DISPLAY_SMOOTHING_SIGMA_CELLS = 5.0
LAGOON_DISPLAY_SMOOTHING_RADIUS_CELLS = 4.0
PIL_BICUBIC = Image.Resampling.BICUBIC
PIL_LANCZOS = Image.Resampling.LANCZOS

PILOT_IDS = (
    "S6-MOOR-CAPITAL-ANCHOR-01",
    "SITE4-A872A7A2208D1A55",
    "S6-SEEL-CATHEDRAL-ANCHOR-01",
    "SITE4-BB29BFB4F83D4C02",
)

HAUS_DISPLAY = {
    "DUNKELHAUCH": "Dunkelhauch",
    "MOORWANDLER": "Moorwandler",
    "SEELENWACHT": "Seelenwacht",
    "FROSTGLANZ": "Frostglanz",
    "FEUERSCHUPPE": "Feuerschuppe",
    "EISENWEB": "Eisenweb",
    "EDELSTEIN": "Edelstein",
    "VERFUEHRSCHLUND": "Verführungsschlund",
    "BUCHHAIN": "Buchhain",
    "NACHTFLUESTERN": "Nachtflüstern",
    "STILLKLINGE": "Stillklinge",
    "ZWIELICHT": "Zwielicht",
    "LAUBRAUNEN": "Laubraunen",
    "MARIENHAIN": "Marienhain",
    "WIEDERGEBORENE_FLAMME": "Wiedergeborene Flamme",
    "EREMITENSCHALE": "Eremitenschale",
    "SERENAKRONE": "Serenakrone",
    "GLANZGRUND": "Glanzgrund",
    "STURMGLAS": "Sturmglas",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = {
        "title": (Path(r"C:\Windows\Fonts\georgiab.ttf"), Path(r"C:\Windows\Fonts\cambria.ttc")),
        "semibold": (Path(r"C:\Windows\Fonts\seguisb.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf")),
        "body": (Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\arial.ttf")),
    }
    for path in candidates[name]:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


TITLE_FONT = _font("title", 42)
SUBTITLE_FONT = _font("body", 23)
STATUS_FONT = _font("semibold", 19)
BODY_FONT = _font("body", 18)
SMALL_FONT = _font("body", 15)
LABEL_FONT = _font("semibold", 22)
CONTEXT_FONT = _font("semibold", 17)


def pchip_slopes(values: np.ndarray) -> np.ndarray:
    """Shape-preserving cubic slopes for a uniform one-dimensional grid."""

    y = np.asarray(values, dtype=np.float64)
    if y.ndim != 1 or y.size < 2:
        raise ValueError("PCHIP input must be a one-dimensional sequence of at least two values")
    delta = np.diff(y)
    slopes = np.zeros_like(y)
    if y.size == 2:
        slopes[:] = delta[0]
        return slopes
    compatible = delta[:-1] * delta[1:] > 0.0
    slopes[1:-1][compatible] = (
        2.0 * delta[:-1][compatible] * delta[1:][compatible]
        / (delta[:-1][compatible] + delta[1:][compatible])
    )

    first = (3.0 * delta[0] - delta[1]) / 2.0
    if np.sign(first) != np.sign(delta[0]):
        first = 0.0
    elif np.sign(delta[0]) != np.sign(delta[1]) and abs(first) > 3.0 * abs(delta[0]):
        first = 3.0 * delta[0]
    last = (3.0 * delta[-1] - delta[-2]) / 2.0
    if np.sign(last) != np.sign(delta[-1]):
        last = 0.0
    elif np.sign(delta[-1]) != np.sign(delta[-2]) and abs(last) > 3.0 * abs(delta[-1]):
        last = 3.0 * delta[-1]
    slopes[0] = first
    slopes[-1] = last
    return slopes


def pchip_resample_1d(values: np.ndarray, factor: int = 10) -> np.ndarray:
    """Evaluate a shape-preserving cubic at fine-cell centres."""

    y = np.asarray(values, dtype=np.float64)
    slopes = pchip_slopes(y)
    positions = (np.arange(y.size * factor, dtype=np.float64) + 0.5) / factor
    result = np.empty_like(positions)
    left = positions <= 0.5
    right = positions >= y.size - 0.5
    result[left] = y[0]
    result[right] = y[-1]
    middle = ~(left | right)
    interval = np.floor(positions[middle] - 0.5).astype(np.int64)
    t = positions[middle] - (interval + 0.5)
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2
    result[middle] = (
        h00 * y[interval]
        + h10 * slopes[interval]
        + h01 * y[interval + 1]
        + h11 * slopes[interval + 1]
    )
    return np.clip(result, float(np.min(y)), float(np.max(y)))


def pchip_surface(parent: np.ndarray, factor: int = 10) -> np.ndarray:
    parent = np.asarray(parent, dtype=np.float64)
    horizontal = np.vstack([pchip_resample_1d(row, factor) for row in parent])
    vertical = np.column_stack(
        [pchip_resample_1d(horizontal[:, column], factor) for column in range(horizontal.shape[1])]
    )
    return np.clip(vertical, float(np.min(parent)), float(np.max(parent)))


def display_elevation(base: np.ndarray, conditioned: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if base.shape != (FINE_CELLS, FINE_CELLS):
        raise ValueError(f"Unexpected terrain shape: {base.shape}")
    parent = np.asarray(base, dtype=np.float64).reshape(30, 10, 30, 10).mean(axis=(1, 3))
    continuous = pchip_surface(parent)
    residual = np.asarray(conditioned, dtype=np.float64) - np.asarray(base, dtype=np.float64)
    return continuous + residual, parent


def multidirectional_hillshade(elevation: np.ndarray, vertical_exaggeration: float = 2.0) -> np.ndarray:
    value = np.asarray(elevation, dtype=np.float64)
    south_gradient, east_gradient = np.gradient(value * vertical_exaggeration, 10.0, 10.0)
    north_gradient = -south_gradient
    nx = -east_gradient
    ny = -north_gradient
    nz = np.ones_like(value)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / norm, ny / norm, nz / norm
    illumination = np.zeros_like(value)
    for azimuth, weight in ((315.0, 0.55), (45.0, 0.15), (225.0, 0.15), (135.0, 0.15)):
        az = math.radians(azimuth)
        altitude = math.radians(38.0)
        lx = math.sin(az) * math.cos(altitude)
        ly = math.cos(az) * math.cos(altitude)
        lz = math.sin(altitude)
        illumination += weight * np.clip(nx * lx + ny * ly + nz * lz, 0.0, 1.0)
    return np.clip(illumination, 0.0, 1.0)


def _palette(metadata: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    text = " ".join(
        str(metadata.get(key) or "")
        for key in ("leading_formation_name", "secondary_formation_name", "climate_descriptor")
    ).lower()
    if metadata.get("wetland_fraction", 0.0) >= 0.25:
        return np.array([91, 118, 98]), np.array([127, 145, 111]), np.array([175, 174, 130])
    if "nival" in text or "perennial-snow" in text or "polar" in text:
        return np.array([137, 151, 151]), np.array([173, 181, 177]), np.array([224, 226, 220])
    if "alpine" in text or "fellfield" in text or "tundra" in text:
        return np.array([126, 137, 120]), np.array([158, 158, 133]), np.array([205, 198, 169])
    if "dry steppe" in text or "scrub" in text or "very cold dry" in text:
        return np.array([132, 126, 91]), np.array([166, 153, 105]), np.array([205, 190, 145])
    if "macroforest" in text or "forest" in text or "woodland" in text or "conifer" in text:
        return np.array([78, 112, 78]), np.array([118, 139, 93]), np.array([177, 168, 121])
    if "grassland" in text or "meadow" in text:
        return np.array([111, 132, 82]), np.array([156, 154, 94]), np.array([199, 179, 123])
    return np.array([112, 128, 103]), np.array([151, 151, 116]), np.array([196, 184, 149])


def gaussian_blur_array(values: np.ndarray, sigma_cells: float) -> np.ndarray:
    """Blur a numerical display surface without changing the analytical arrays."""

    source = np.asarray(values, dtype=np.float64)
    if sigma_cells <= 0.0:
        return source.copy()
    radius = max(1, int(math.ceil(3.0 * sigma_cells)))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / sigma_cells) ** 2)
    kernel /= np.sum(kernel)

    finite = np.isfinite(source)
    filled = np.where(finite, source, 0.0)
    weights = finite.astype(np.float64)

    def convolve_axis(array: np.ndarray, axis: int) -> np.ndarray:
        padding = [(0, 0), (0, 0)]
        padding[axis] = (radius, radius)
        padded = np.pad(array, padding, mode="reflect")
        return np.apply_along_axis(lambda line: np.convolve(line, kernel, mode="valid"), axis, padded)

    blurred = convolve_axis(convolve_axis(filled, 1), 0)
    blurred_weights = convolve_axis(convolve_axis(weights, 1), 0)
    result = np.divide(blurred, blurred_weights, out=np.full_like(blurred, np.nan), where=blurred_weights > 1e-12)
    result[~finite] = np.nan
    return result


def terrain_rgb(
    elevation: np.ndarray,
    metadata: Mapping[str, Any],
    relief_surface: np.ndarray | None = None,
) -> np.ndarray:
    finite = np.isfinite(elevation)
    low, high = np.percentile(elevation[finite], (2.0, 98.0))
    relative = np.clip((elevation - low) / max(float(high - low), 1e-6), 0.0, 1.0)
    c0, c1, c2 = _palette(metadata)
    first = np.clip(relative * 2.0, 0.0, 1.0)[..., None]
    second = np.clip((relative - 0.5) * 2.0, 0.0, 1.0)[..., None]
    colour = c0 * (1.0 - first) + c1 * first
    colour = colour * (1.0 - second) + c2 * second
    shade = multidirectional_hillshade(elevation if relief_surface is None else relief_surface)
    # A small, bounded local contrast contribution makes broad terrain legible
    # without the aggressive stretch that exposed 100 m parent-cell seams.
    shade_low, shade_high = np.percentile(shade[finite], (5.0, 95.0))
    if float(shade_high - shade_low) >= 0.02:
        local = np.clip((shade - shade_low) / (shade_high - shade_low), 0.0, 1.0)
        shade = 0.86 * shade + 0.14 * local
    factor = (0.59 + 0.68 * shade)[..., None]
    colour = np.clip(colour * factor, 0.0, 255.0)
    colour[~finite] = np.array([220, 220, 215])
    return colour.astype(np.uint8)


def nice_contour_interval(elevation: np.ndarray) -> float | None:
    finite = elevation[np.isfinite(elevation)]
    relief = float(np.percentile(finite, 99.0) - np.percentile(finite, 1.0))
    if relief < 1.0:
        return None
    raw = max(relief / 12.0, 0.5)
    exponent = math.floor(math.log10(raw))
    scaled = raw / (10.0 ** exponent)
    step = 1.0 if scaled <= 1.0 else 2.0 if scaled <= 2.0 else 5.0 if scaled <= 5.0 else 10.0
    return step * (10.0 ** exponent)


def _edge_intersection(a: float, b: float, level: float) -> float:
    if a == b:
        return 0.5
    return float(np.clip((level - a) / (b - a), 0.0, 1.0))


def contour_segments(
    elevation: np.ndarray,
    level: float,
    excluded: np.ndarray | None = None,
) -> Iterable[tuple[tuple[float, float], tuple[float, float]]]:
    z = np.asarray(elevation, dtype=np.float64)
    height, width = z.shape
    for row in range(height - 1):
        for column in range(width - 1):
            if excluded is not None and bool(np.any(excluded[row : row + 2, column : column + 2])):
                continue
            p00, p01 = z[row, column], z[row, column + 1]
            p11, p10 = z[row + 1, column + 1], z[row + 1, column]
            if not np.isfinite((p00, p01, p11, p10)).all():
                continue
            points: list[tuple[int, tuple[float, float]]] = []
            if (p00 < level) != (p01 < level):
                t = _edge_intersection(p00, p01, level)
                points.append((0, (column + t + 0.5, row + 0.5)))
            if (p01 < level) != (p11 < level):
                t = _edge_intersection(p01, p11, level)
                points.append((1, (column + 1.5, row + t + 0.5)))
            if (p11 < level) != (p10 < level):
                t = _edge_intersection(p11, p10, level)
                points.append((2, (column + 1.5 - t, row + 1.5)))
            if (p10 < level) != (p00 < level):
                t = _edge_intersection(p10, p00, level)
                points.append((3, (column + 0.5, row + 1.5 - t)))
            if len(points) == 2:
                yield points[0][1], points[1][1]
            elif len(points) == 4:
                by_edge = {edge: point for edge, point in points}
                centre_above = (p00 + p01 + p11 + p10) / 4.0 >= level
                pairs = ((0, 1), (2, 3)) if centre_above else ((0, 3), (1, 2))
                for first, second in pairs:
                    yield by_edge[first], by_edge[second]


def _draw_contours(
    image: Image.Image,
    elevation: np.ndarray,
    interval: float | None,
    excluded: np.ndarray | None = None,
) -> None:
    if interval is None:
        return
    draw = ImageDraw.Draw(image, "RGBA")
    minimum = float(np.nanmin(elevation))
    maximum = float(np.nanmax(elevation))
    first = math.ceil(minimum / interval) * interval
    levels = np.arange(first, maximum + interval * 0.1, interval)
    if len(levels) > 20:
        levels = levels[:: math.ceil(len(levels) / 20)]
    scale = WORK_PX / FINE_CELLS
    for level_index, level in enumerate(levels):
        index = int(round(level / interval))
        index_contour = index % 5 == 0
        fill = (79, 67, 52, 56 if index_contour else 29)
        width = 2 if index_contour else 1
        segments = [LineString((start, end)) for start, end in contour_segments(elevation, float(level), excluded)]
        if not segments:
            continue
        merged = shapely.line_merge(shapely.union_all(segments))
        for line in _line_parts(merged):
            # Small or narrow closed loops are not supportable landforms at the
            # 100 m authority scale; suppress them rather than presenting
            # interpolation pills as real knolls or hollows.
            if line.is_closed:
                perimeter_km = float(line.length) * FINE_CELL_KM
                area_km2 = abs(float(Polygon(line).area)) * FINE_CELL_KM**2
                if (
                    perimeter_km < MINIMUM_CLOSED_CONTOUR_PERIMETER_KM
                    or area_km2 < MINIMUM_CLOSED_CONTOUR_AREA_KM2
                ):
                    continue
            points = [
                (int(round(float(item[0]) * scale)), int(round(float(item[1]) * scale)))
                for item in line.coords
            ]
            draw.line(points, fill=fill, width=width * OVERSAMPLE, joint="curve")


def categorical_display_mask(mask: np.ndarray, radius_cells: float = LAGOON_DISPLAY_SMOOTHING_RADIUS_CELLS) -> np.ndarray:
    """Interpret a coarse category continuously while preserving its area.

    Stage 6C.5R stores the 100 m categorical parent value on each of its ten
    10 m children.  Resampling that block projection directly merely enlarges
    the staircase.  Reconstructing the 30 x 30 parent first lets the display
    boundary cross each 100 m evidence cell continuously; the retained-cell
    threshold prevents the visual treatment from adding or removing water.
    """

    binary = np.asarray(mask, dtype=np.float32) >= 0.5
    count = int(np.count_nonzero(binary))
    if count == 0 or count == binary.size:
        return binary.astype(np.float32)
    if binary.shape == (FINE_CELLS, FINE_CELLS) and FINE_CELLS % 10 == 0:
        parent = binary.reshape(30, 10, 30, 10).mean(axis=(1, 3))
        source = Image.fromarray((parent * 255.0).astype(np.uint8), mode="L").resize(
            (FINE_CELLS, FINE_CELLS), PIL_BICUBIC
        )
        # A light bounded finish removes interpolation ripples without hiding
        # the parent evidence.  The total display corridor remains half of one
        # 100 m source cell.
        finish_radius = max(0.0, radius_cells - 3.0)
    else:
        source = Image.fromarray((binary.astype(np.uint8) * 255), mode="L")
        finish_radius = radius_cells
    if finish_radius > 0.0:
        source = source.filter(ImageFilter.GaussianBlur(radius=finish_radius))
    blurred = np.asarray(source, dtype=np.float32)
    threshold = float(np.partition(blurred.ravel(), -count)[-count])
    rounded = blurred >= threshold
    softened = Image.fromarray((rounded.astype(np.uint8) * 255), mode="L").filter(
        ImageFilter.GaussianBlur(radius=0.7)
    )
    return np.asarray(softened, dtype=np.float32) / 255.0


def natural_water_display_mask(mask: np.ndarray) -> np.ndarray:
    """Create a continuous shoreline from an edge-connected coarse mask.

    This is used only for cartography.  It retains the exact number of water
    cells, but replaces a monotone edge staircase with a regularised boundary.
    Complex or enclosed water shapes fall back to the conservative categorical
    interpolation above.
    """

    binary = np.asarray(mask, dtype=np.float32) >= 0.5
    if binary.shape != (FINE_CELLS, FINE_CELLS) or FINE_CELLS % 10:
        return categorical_display_mask(binary)
    parent = binary.reshape(30, 10, 30, 10).mean(axis=(1, 3)) >= 0.5
    height, width = parent.shape

    candidates: list[tuple[int, str, np.ndarray]] = []
    for side in ("right", "left"):
        boundary = np.empty(height, dtype=np.float64)
        valid_partial = 0
        valid = True
        for row_index, row in enumerate(parent):
            indices = np.flatnonzero(row)
            if indices.size == 0:
                boundary[row_index] = float(width if side == "right" else 0)
                continue
            if indices.size == width:
                boundary[row_index] = float(0 if side == "right" else width)
                continue
            contiguous = bool(np.all(np.diff(indices) == 1))
            touches = bool(indices[-1] == width - 1) if side == "right" else bool(indices[0] == 0)
            if not contiguous or not touches:
                valid = False
                break
            boundary[row_index] = float(indices[0] if side == "right" else indices[-1] + 1)
            valid_partial += 1
        if valid and valid_partial >= 3:
            differences = np.diff(boundary)
            monotone_score = max(
                int(np.count_nonzero(differences >= -1e-9)),
                int(np.count_nonzero(differences <= 1e-9)),
            )
            candidates.append((monotone_score, side, boundary))
    if not candidates:
        return categorical_display_mask(binary)

    monotone_score, side, boundary = max(candidates, key=lambda item: item[0])
    if monotone_score < height - 4:
        return categorical_display_mask(binary)

    # Penalised second differences remove raster stair steps while retaining
    # the broad source shape.  This is deterministic and has no random detail.
    second_difference = np.zeros((height - 2, height), dtype=np.float64)
    for index in range(height - 2):
        second_difference[index, index : index + 3] = (1.0, -2.0, 1.0)
    regularised = np.linalg.solve(
        np.eye(height) + second_difference.T @ second_difference,
        boundary,
    )
    regularised = np.clip(regularised, 0.0, float(width))
    fine_boundary = pchip_resample_1d(regularised, 10) * 10.0
    x_centres = np.arange(FINE_CELLS, dtype=np.float64)[None, :] + 0.5
    if side == "right":
        signed = x_centres - fine_boundary[:, None]
    else:
        signed = fine_boundary[:, None] - x_centres

    target_count = int(np.count_nonzero(binary))
    if target_count == 0 or target_count == binary.size:
        return binary.astype(np.float32)
    # Stable infinitesimal ordering avoids a threshold tie changing the area.
    signed = signed + np.arange(binary.size, dtype=np.float64).reshape(binary.shape) * 1e-12
    threshold = float(np.partition(signed.ravel(), -target_count)[-target_count])
    continuous = np.clip(0.5 + (signed - threshold) / 1.4, 0.0, 1.0)
    # Interpolate between successive 10 m rows as well as across the shore.
    # This removes the final fine scallop without moving the source mask or
    # inventing coastal detail.
    continuous = gaussian_blur_array(continuous, 0.85)
    stable = continuous + np.arange(binary.size, dtype=np.float64).reshape(binary.shape) * 1e-12
    threshold = float(np.partition(stable.ravel(), -target_count)[-target_count])
    return np.clip(0.5 + (stable - threshold) * 1.8, 0.0, 1.0).astype(np.float32)


def _soft_mask(mask: np.ndarray, radius_cells: float, output_size: int = WORK_PX) -> Image.Image:
    source = Image.fromarray((np.clip(mask, 0.0, 1.0) * 255.0).astype(np.uint8), mode="L")
    if radius_cells > 0:
        source = source.filter(ImageFilter.GaussianBlur(radius=radius_cells))
    return source.resize((output_size, output_size), PIL_LANCZOS)


def _blend_colour(image: Image.Image, mask: np.ndarray, colour: tuple[int, int, int], alpha: int, blur: float) -> Image.Image:
    layer = Image.new("RGB", image.size, colour)
    opacity = _soft_mask(mask, blur)
    opacity = opacity.point(lambda value: int(value * alpha / 255.0))
    return Image.composite(layer, image, opacity)


def _line_parts(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        result: list[LineString] = []
        for part in geometry.geoms:
            result.extend(_line_parts(part))
        return result
    return []


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        result: list[Polygon] = []
        for part in geometry.geoms:
            result.extend(_polygon_parts(part))
        return result
    return []


def _coord_key(coordinate: Sequence[float]) -> tuple[int, int]:
    return int(round(float(coordinate[0]) * 1_000_000)), int(round(float(coordinate[1]) * 1_000_000))


def chaikin_segment(coordinates: Sequence[Sequence[float]], iterations: int = 2) -> list[tuple[float, float]]:
    points = [(float(item[0]), float(item[1])) for item in coordinates]
    for _ in range(iterations):
        if len(points) < 3:
            break
        refined = [points[0]]
        for first, second in zip(points[:-1], points[1:]):
            refined.append((0.75 * first[0] + 0.25 * second[0], 0.75 * first[1] + 0.25 * second[1]))
            refined.append((0.25 * first[0] + 0.75 * second[0], 0.25 * first[1] + 0.75 * second[1]))
        refined.append(points[-1])
        points = refined
    return points


def broad_smooth_segment(
    coordinates: Sequence[Sequence[float]],
    sigma_km: float = 0.30,
    station_km: float = 0.02,
) -> list[tuple[float, float]]:
    """Remove one-cell hooks while preserving exact interval endpoints.

    The registered minor routes inherit some 100 m routing-grid detours. A
    broad one-dimensional Gaussian fit removes those display artefacts before
    the bounded irregular curvature is applied. Final corridor validation
    still limits every accepted line to the source uncertainty corridor.
    """

    line = LineString(coordinates)
    length = float(line.length)
    if length < 0.24 or sigma_km <= 0.0:
        return [(float(item[0]), float(item[1])) for item in coordinates]
    count = max(4, int(math.ceil(length / station_km)))
    distances = np.linspace(0.0, length, count + 1)
    source = np.asarray(
        [(float(point.x), float(point.y)) for point in (line.interpolate(float(distance)) for distance in distances)],
        dtype=np.float64,
    )
    sigma_stations = max(1.0, sigma_km / max(length / count, 1e-9))
    radius = max(1, int(math.ceil(3.0 * sigma_stations)))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / sigma_stations) ** 2)
    kernel /= np.sum(kernel)
    padded = np.pad(source, ((radius, radius), (0, 0)), mode="reflect")
    smooth = np.column_stack(
        [np.convolve(padded[:, axis], kernel, mode="valid") for axis in range(2)]
    )
    anchor_ramp_km = min(0.06, length / 2.0)
    envelope = np.minimum(1.0, distances / max(anchor_ramp_km, 1e-9))
    envelope *= np.minimum(1.0, (length - distances) / max(anchor_ramp_km, 1e-9))
    envelope = np.sin(np.clip(envelope, 0.0, 1.0) * math.pi / 2.0) ** 0.8
    result = source + envelope[:, None] * (smooth - source)
    result[0] = source[0]
    result[-1] = source[-1]
    return [(float(item[0]), float(item[1])) for item in result]


def soften_confluence_approach(
    coordinates: Sequence[Sequence[float]],
    span_km: float = 0.45,
) -> list[tuple[float, float]]:
    """Replace a last-cell hook with one smooth exact confluence approach."""

    line = LineString(coordinates)
    length = float(line.length)
    span = min(span_km, length * 0.45)
    if span < 0.12:
        return [(float(item[0]), float(item[1])) for item in coordinates]
    join_distance = length - span
    join = line.interpolate(join_distance)
    before = line.interpolate(max(0.0, join_distance - 0.06))
    end = line.interpolate(length)
    chord_x, chord_y = float(end.x - join.x), float(end.y - join.y)
    chord_norm = math.hypot(chord_x, chord_y)
    tangent_x, tangent_y = float(join.x - before.x), float(join.y - before.y)
    tangent_norm = math.hypot(tangent_x, tangent_y)
    if chord_norm <= 1e-12:
        return [(float(item[0]), float(item[1])) for item in coordinates]
    chord_x, chord_y = chord_x / chord_norm, chord_y / chord_norm
    if tangent_norm <= 1e-12 or tangent_x * chord_x + tangent_y * chord_y <= 0.0:
        tangent_x, tangent_y = chord_x, chord_y
    else:
        tangent_x, tangent_y = tangent_x / tangent_norm, tangent_y / tangent_norm
    control = span / 3.0
    p0 = np.asarray((float(join.x), float(join.y)), dtype=np.float64)
    p1 = p0 + control * np.asarray((tangent_x, tangent_y), dtype=np.float64)
    p3 = np.asarray((float(end.x), float(end.y)), dtype=np.float64)
    p2 = p3 - control * np.asarray((chord_x, chord_y), dtype=np.float64)
    prefix_distances = np.arange(0.0, max(0.0, join_distance - 1e-9), 0.02)
    result = [
        (float(point.x), float(point.y))
        for point in (line.interpolate(float(distance)) for distance in prefix_distances)
    ]
    result.append((float(p0[0]), float(p0[1])))
    curve_count = max(4, int(math.ceil(span / 0.02)))
    for t in np.linspace(0.0, 1.0, curve_count + 1)[1:]:
        point = (
            (1.0 - t) ** 3 * p0
            + 3.0 * (1.0 - t) ** 2 * t * p1
            + 3.0 * (1.0 - t) * t * t * p2
            + t**3 * p3
        )
        result.append((float(point[0]), float(point[1])))
    result[-1] = (float(line.coords[-1][0]), float(line.coords[-1][1]))
    return result


def add_subcell_curvature(
    coordinates: Sequence[Sequence[float]],
    amplitude_km: float = MINOR_SUBCELL_CURVATURE_AMPLITUDE_KM,
) -> list[tuple[float, float]]:
    """Remove implausibly perfect long axes within the 100 m evidence cell."""

    line = LineString(coordinates)
    length = float(line.length)
    if length < 0.25 or amplitude_km <= 0.0:
        return [(float(item[0]), float(item[1])) for item in coordinates]
    count = max(3, int(math.ceil(length / 0.04)))
    distances = np.linspace(0.0, length, count + 1)
    first = line.coords[0]
    last = line.coords[-1]
    phase_seed = abs(
        int(round((float(first[0]) + float(last[0])) * 10_000))
        ^ int(round((float(first[1]) + float(last[1])) * 10_000))
    )
    phase = (phase_seed % 6283) / 1000.0
    result: list[tuple[float, float]] = []
    tangent_window = min(0.03, length / 8.0)
    for index, distance in enumerate(distances):
        point = line.interpolate(float(distance))
        if index in (0, count):
            result.append((float(point.x), float(point.y)))
            continue
        before = line.interpolate(max(0.0, float(distance) - tangent_window))
        after = line.interpolate(min(length, float(distance) + tangent_window))
        dx, dy = float(after.x - before.x), float(after.y - before.y)
        norm = math.hypot(dx, dy)
        if norm <= 1e-12:
            result.append((float(point.x), float(point.y)))
            continue
        progress = float(distance) / length
        taper = math.sin(math.pi * progress) ** 2
        offset = amplitude_km * taper * (
            0.76 * math.sin(2.0 * math.pi * float(distance) / 0.72 + phase)
            + 0.24 * math.sin(2.0 * math.pi * float(distance) / 1.31 + 1.7 * phase)
        )
        result.append((float(point.x) - dy / norm * offset, float(point.y) + dx / norm * offset))
    result[0] = (float(first[0]), float(first[1]))
    result[-1] = (float(last[0]), float(last[1]))
    return result


def _bilinear_grid_sample(
    values: np.ndarray,
    x_km: float,
    y_km: float,
    bounds: tuple[float, float, float, float],
) -> float:
    """Sample a lens grid whose coordinates describe cell edges."""

    xmin, ymin, xmax, ymax = bounds
    height, width = values.shape
    column = (x_km - xmin) / (xmax - xmin) * width - 0.5
    row = (y_km - ymin) / (ymax - ymin) * height - 0.5
    if column < -0.5 or row < -0.5 or column > width - 0.5 or row > height - 0.5:
        return math.nan
    column = float(np.clip(column, 0.0, width - 1.0))
    row = float(np.clip(row, 0.0, height - 1.0))
    c0, r0 = int(math.floor(column)), int(math.floor(row))
    c1, r1 = min(c0 + 1, width - 1), min(r0 + 1, height - 1)
    tx, ty = column - c0, row - r0
    samples = np.asarray((values[r0, c0], values[r0, c1], values[r1, c0], values[r1, c1]), dtype=np.float64)
    if not np.isfinite(samples).all():
        return math.nan
    return float(
        samples[0] * (1.0 - tx) * (1.0 - ty)
        + samples[1] * tx * (1.0 - ty)
        + samples[2] * (1.0 - tx) * ty
        + samples[3] * tx * ty
    )


def _irregular_curvature_prior(
    distances: np.ndarray,
    line: LineString,
    amplitude_km: float,
) -> np.ndarray:
    """Return a deterministic, non-periodic display prior within uncertainty."""

    length = float(line.length)
    seed = (
        f"{float(line.coords[0][0]):.6f},{float(line.coords[0][1]):.6f}:"
        f"{float(line.coords[-1][0]):.6f},{float(line.coords[-1][1]):.6f}"
    )
    controls = [0.0]
    index = 0
    while controls[-1] < length:
        digest = sha256(f"{seed}:spacing:{index}".encode("utf-8")).digest()
        unit = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        next_position = controls[-1] + 0.24 + 0.22 * unit
        if length - next_position < 0.18:
            break
        controls.append(next_position)
        index += 1
    controls.append(length)
    offsets = np.zeros(len(controls), dtype=np.float64)
    previous_sign = 1.0 if sha256(seed.encode("utf-8")).digest()[0] & 1 else -1.0
    for index in range(1, len(controls) - 1):
        digest = sha256(f"{seed}:offset:{index}".encode("utf-8")).digest()
        # Mostly alternating turns prevent long grid-parallel shelves, while
        # occasional repeated signs avoid a mechanical sine-wave rhythm.
        repeat = digest[0] < 54
        sign = previous_sign if repeat else -previous_sign
        magnitude = 0.66 + 0.31 * (int.from_bytes(digest[1:9], "big") / float(2**64 - 1))
        offsets[index] = sign * amplitude_km * magnitude
        previous_sign = sign
    prior = np.interp(distances, np.asarray(controls, dtype=np.float64), offsets)
    progress = np.divide(distances, length, out=np.zeros_like(distances), where=length > 0.0)
    prior *= np.sin(np.pi * progress) ** 0.72

    # A control-point sign change immediately beside a protected endpoint can
    # create a conspicuous hook at a headwater or confluence. Keep a neutral
    # endpoint zone; broad smoothing and the explicit confluence fit govern the
    # approach while the irregular prior remains active in the interior.
    approach_km = min(0.46, length / 2.0)
    if approach_km > 1e-9:
        left = distances <= approach_km
        right = distances >= length - approach_km
        prior[left | right] = 0.0
    prior[0] = prior[-1] = 0.0
    return prior


def terrain_guided_segment(
    coordinates: Sequence[Sequence[float]],
    valley_surface: np.ndarray | None,
    bounds: tuple[float, float, float, float] | None,
    amplitude_km: float = MINOR_TERRAIN_GUIDED_OFFSET_KM,
) -> list[tuple[float, float]]:
    """Fit a broad natural centreline inside the source uncertainty corridor.

    Cross-section candidates favour local terrain lows.  Where the terrain
    cannot distinguish a route at 10 m, a deterministic non-periodic prior
    avoids falsely precise ruler-straight cell axes.  It is a display-only
    interpretation and is never fed back into the analytical route.
    """

    line = LineString(coordinates)
    length = float(line.length)
    if length < 0.20 or amplitude_km <= 0.0:
        return [(float(item[0]), float(item[1])) for item in coordinates]
    count = max(4, int(math.ceil(length / 0.02)))
    distances = np.linspace(0.0, length, count + 1)
    points = [line.interpolate(float(distance)) for distance in distances]
    normals: list[tuple[float, float]] = []
    tangent_window = min(0.04, length / 8.0)
    for distance in distances:
        before = line.interpolate(max(0.0, float(distance) - tangent_window))
        after = line.interpolate(min(length, float(distance) + tangent_window))
        dx, dy = float(after.x - before.x), float(after.y - before.y)
        norm = math.hypot(dx, dy)
        normals.append((0.0, 0.0) if norm <= 1e-12 else (-dy / norm, dx / norm))

    half_steps = max(1, int(math.ceil(amplitude_km / 0.005)))
    candidates = np.linspace(-amplitude_km, amplitude_km, 2 * half_steps + 1)
    zero_index = int(np.argmin(np.abs(candidates)))
    prior = _irregular_curvature_prior(distances, line, amplitude_km)
    node_cost = np.full((count + 1, len(candidates)), np.inf, dtype=np.float64)
    # The route source can span tens of kilometres while the map lens is only
    # 3 km.  Anchor influence therefore uses a fixed physical distance rather
    # than a fraction of the whole source feature.
    anchor_taper_km = min(0.16, length / 2.0)
    taper = np.minimum(1.0, distances / max(anchor_taper_km, 1e-9))
    taper *= np.minimum(1.0, (length - distances) / max(anchor_taper_km, 1e-9))
    taper = np.sin(np.clip(taper, 0.0, 1.0) * math.pi / 2.0) ** 0.72
    for station, (point, normal) in enumerate(zip(points, normals)):
        allowed = np.abs(candidates) <= amplitude_km * taper[station] + 1e-12
        if station in (0, count):
            allowed[:] = False
            allowed[zero_index] = True
        terrain_values = np.full(len(candidates), np.nan, dtype=np.float64)
        if valley_surface is not None and bounds is not None:
            for candidate_index, offset in enumerate(candidates):
                if not allowed[candidate_index]:
                    continue
                terrain_values[candidate_index] = _bilinear_grid_sample(
                    valley_surface,
                    float(point.x) + normal[0] * float(offset),
                    float(point.y) + normal[1] * float(offset),
                    bounds,
                )
        finite = np.isfinite(terrain_values) & allowed
        terrain_score = np.zeros(len(candidates), dtype=np.float64)
        terrain_weight = 0.0
        if np.count_nonzero(finite) >= 2:
            low = float(np.min(terrain_values[finite]))
            high = float(np.max(terrain_values[finite]))
            if high - low >= 0.50:
                terrain_score[finite] = (terrain_values[finite] - low) / (high - low)
                terrain_weight = 0.13
        # Terrain is useful for the broad interior fit, but a local low beside
        # an exact endpoint can pull the curve into a hook immediately before
        # a confluence. Keep the final 460 m governed by the monotone approach
        # prior and the protected endpoint instead.
        if min(float(distances[station]), length - float(distances[station])) < min(0.46, length / 2.0):
            terrain_weight = 0.0
        node_cost[station, allowed] = (
            0.03 * (candidates[allowed] / amplitude_km) ** 2
            + 0.43 * ((candidates[allowed] - prior[station]) / amplitude_km) ** 2
            + terrain_weight * terrain_score[allowed]
        )

    cost = np.full_like(node_cost, np.inf)
    parents = np.full(node_cost.shape, -1, dtype=np.int16)
    cost[0, zero_index] = node_cost[0, zero_index]
    transition_scale = max(amplitude_km / 3.5, 1e-6)
    for station in range(1, count + 1):
        for current in np.flatnonzero(np.isfinite(node_cost[station])):
            transitions = cost[station - 1] + 0.16 * (
                (float(candidates[current]) - candidates) / transition_scale
            ) ** 2
            previous = int(np.argmin(transitions))
            if np.isfinite(transitions[previous]):
                cost[station, current] = node_cost[station, current] + transitions[previous]
                parents[station, current] = previous
    chosen = np.zeros(count + 1, dtype=np.float64)
    current = zero_index
    for station in range(count, -1, -1):
        chosen[station] = candidates[current]
        if station:
            current = int(parents[station, current])
            if current < 0:
                return [(float(item[0]), float(item[1])) for item in coordinates]
    for _ in range(3):
        chosen[1:-1] = (chosen[:-2] + 2.0 * chosen[1:-1] + chosen[2:]) / 4.0
    chosen = np.clip(chosen, -amplitude_km * taper, amplitude_km * taper)
    chosen[0] = chosen[-1] = 0.0
    result = [
        (float(point.x) + normal[0] * float(offset), float(point.y) + normal[1] * float(offset))
        for point, normal, offset in zip(points, normals, chosen)
    ]
    result[0] = (float(line.coords[0][0]), float(line.coords[0][1]))
    result[-1] = (float(line.coords[-1][0]), float(line.coords[-1][1]))
    result = chaikin_segment(result, iterations=1)
    result[0] = (float(line.coords[0][0]), float(line.coords[0][1]))
    result[-1] = (float(line.coords[-1][0]), float(line.coords[-1][1]))
    return result


def bounded_curve_blend(
    source: LineString,
    proposal: LineString,
    max_displacement_km: float,
) -> tuple[LineString, float]:
    """Retain as much fitted curvature as the source corridor permits."""

    corridor_limit = max(0.0, max_displacement_km - 0.001)

    def corridor_ok(candidate: LineString) -> bool:
        return bool(
            source.buffer(corridor_limit, quad_segs=16).covers(candidate)
            and candidate.buffer(corridor_limit, quad_segs=16).covers(source)
        )

    displacement = float(shapely.hausdorff_distance(source, proposal))
    if proposal.is_simple and corridor_ok(proposal):
        return proposal, displacement

    sample_count = max(8, int(math.ceil(max(float(source.length), float(proposal.length)) / 0.02)) + 1)

    def blend(alpha: float) -> LineString:
        points: list[tuple[float, float]] = []
        for fraction in np.linspace(0.0, 1.0, sample_count):
            source_point = source.interpolate(float(fraction), normalized=True)
            proposal_point = proposal.interpolate(float(fraction), normalized=True)
            points.append(
                (
                    float(source_point.x) + alpha * float(proposal_point.x - source_point.x),
                    float(source_point.y) + alpha * float(proposal_point.y - source_point.y),
                )
            )
        points[0] = (float(source.coords[0][0]), float(source.coords[0][1]))
        points[-1] = (float(source.coords[-1][0]), float(source.coords[-1][1]))
        return LineString(points)

    low, high = 0.0, 1.0
    best, best_displacement = source, 0.0
    for _ in range(14):
        alpha = (low + high) / 2.0
        candidate = blend(alpha)
        candidate_displacement = float(shapely.hausdorff_distance(source, candidate))
        if candidate.is_simple and corridor_ok(candidate):
            best, best_displacement = candidate, candidate_displacement
            low = alpha
        else:
            high = alpha
    return best, best_displacement


def topology_locked_smoothing(
    geometry: LineString,
    protected_keys: set[tuple[int, int]],
    confluence_keys: set[tuple[int, int]] | None = None,
    valley_surface: np.ndarray | None = None,
    bounds: tuple[float, float, float, float] | None = None,
    max_displacement_km: float = MINOR_MAX_DISPLACEMENT_KM,
) -> tuple[LineString, float, int]:
    confluence_keys = confluence_keys or set()
    coordinates = list(geometry.coords)
    fixed = [0]
    fixed.extend(
        index
        for index in range(1, len(coordinates) - 1)
        if _coord_key(coordinates[index]) in protected_keys
    )
    fixed.append(len(coordinates) - 1)
    fixed = sorted(set(fixed))
    result: list[tuple[float, float]] = []
    for start, end in zip(fixed[:-1], fixed[1:]):
        source_segment = LineString(coordinates[start : end + 1]).simplify(0.012, preserve_topology=True)
        segment = broad_smooth_segment(source_segment.coords, sigma_km=0.30)
        segment = terrain_guided_segment(segment, valley_surface, bounds)
        if _coord_key(source_segment.coords[-1]) in confluence_keys:
            segment = soften_confluence_approach(segment)
        if result:
            segment = segment[1:]
        result.extend(segment)
    candidate = LineString(result)
    displacement = float(shapely.hausdorff_distance(geometry, candidate))
    if displacement > max_displacement_km + 1e-9:
        result = []
        for start, end in zip(fixed[:-1], fixed[1:]):
            source_segment = LineString(coordinates[start : end + 1]).simplify(0.008, preserve_topology=True)
            segment = broad_smooth_segment(source_segment.coords, sigma_km=0.18)
            segment = terrain_guided_segment(
                segment,
                valley_surface,
                bounds,
                amplitude_km=MINOR_TERRAIN_GUIDED_OFFSET_KM / 2.0,
            )
            if _coord_key(source_segment.coords[-1]) in confluence_keys:
                segment = soften_confluence_approach(segment)
            if result:
                segment = segment[1:]
            result.extend(segment)
        candidate = LineString(result)
        displacement = float(shapely.hausdorff_distance(geometry, candidate))
    candidate, displacement = bounded_curve_blend(geometry, candidate, max_displacement_km)
    if _coord_key(candidate.coords[0]) != _coord_key(coordinates[0]) or _coord_key(candidate.coords[-1]) != _coord_key(coordinates[-1]):
        raise RuntimeError("Minor-stream display smoothing moved an endpoint")
    return candidate, displacement, len(fixed)


def _world_to_work(coordinates: Iterable[Sequence[float]], bounds: tuple[float, float, float, float]) -> list[tuple[int, int]]:
    xmin, ymin, xmax, ymax = bounds
    return [
        (
            int(round((float(item[0]) - xmin) / (xmax - xmin) * WORK_PX)),
            int(round((float(item[1]) - ymin) / (ymax - ymin) * WORK_PX)),
        )
        for item in coordinates
    ]


def _draw_round_line(draw: ImageDraw.ImageDraw, points: Sequence[tuple[int, int]], fill: tuple[int, ...], width: int) -> None:
    if len(points) < 2:
        return
    draw.line(points, fill=fill, width=width, joint="curve")
    radius = width // 2
    if radius > 1:
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[int, int]],
    fill: tuple[int, ...],
    width: int,
    dash: int,
    gap: int,
) -> None:
    remaining = float(dash)
    drawing = True
    for first, second in zip(points[:-1], points[1:]):
        x0, y0 = map(float, first)
        x1, y1 = map(float, second)
        length = math.hypot(x1 - x0, y1 - y0)
        if length == 0:
            continue
        travelled = 0.0
        while travelled < length:
            take = min(remaining, length - travelled)
            if drawing:
                a = travelled / length
                b = (travelled + take) / length
                draw.line(
                    (
                        int(round(x0 + (x1 - x0) * a)), int(round(y0 + (y1 - y0) * a)),
                        int(round(x0 + (x1 - x0) * b)), int(round(y0 + (y1 - y0) * b)),
                    ),
                    fill=fill,
                    width=width,
                )
            travelled += take
            remaining -= take
            if remaining <= 1e-9:
                drawing = not drawing
                remaining = float(dash if drawing else gap)


def _route_width(route_class: str) -> int:
    return {
        "titan": 15 * OVERSAMPLE,
        "major": 9 * OVERSAMPLE,
        "tier2": 2 * OVERSAMPLE,
        "tier1": 1 * OVERSAMPLE,
        "special": 3 * OVERSAMPLE,
    }.get(route_class, 2 * OVERSAMPLE)


def _draw_routes(
    image: Image.Image,
    bounds: tuple[float, float, float, float],
    route_rows: Sequence[Mapping[str, Any]],
    major_by_id: Mapping[str, Any],
    minor_by_id: Mapping[str, Any],
    open_water_mask: np.ndarray | None = None,
    terrain_surface: np.ndarray | None = None,
) -> dict[str, Any]:
    extent = box(*bounds)
    fitting_extent = extent.buffer(0.08, join_style="mitre")
    selected: list[tuple[Mapping[str, Any], Any]] = []
    endpoint_annotations: list[dict[str, Any]] = []
    confluence_keys: set[tuple[int, int]] = set()
    seen: set[str] = set()
    for row in route_rows:
        feature_id = str(row["feature_id"])
        if feature_id in seen or not bool(row["physical_route_accepted"]):
            continue
        seen.add(feature_id)
        source = major_by_id if row["source_kind"] == "major" else minor_by_id
        geometry = source.get(feature_id)
        if geometry is None:
            raise RuntimeError(f"Accepted route {feature_id} has no registered source geometry")
        for part in _line_parts(geometry):
            if row["source_kind"] == "minor" and row.get("receiver_id"):
                confluence_keys.add(_coord_key(part.coords[-1]))
            endpoint_specs = (
                (
                    part.coords[0],
                    "registered headwater" if not bool(row.get("boundary_inflow")) else "registered route entry",
                ),
                (
                    part.coords[-1],
                    "to registered receiver" if row.get("receiver_id") else "registered route endpoint",
                ),
            )
            for coordinate, label in endpoint_specs:
                x_km, y_km = float(coordinate[0]), float(coordinate[1])
                if bounds[0] + 0.06 < x_km < bounds[2] - 0.06 and bounds[1] + 0.06 < y_km < bounds[3] - 0.06:
                    endpoint_annotations.append(
                        {
                            "feature_id": feature_id,
                            "coordinate_km": [x_km, y_km],
                            "label": label,
                        }
                    )
        # Fit only the local lens plus a small off-map continuation.  The
        # registered feature may be tens of kilometres long; fitting that
        # entire object would make local anchors and terrain irrelevant.
        local_geometry = geometry.intersection(fitting_extent)
        if not local_geometry.is_empty:
            selected.append((row, local_geometry))

    protected_keys: set[tuple[int, int]] = set()
    for _, geometry in selected:
        for part in _line_parts(geometry):
            protected_keys.add(_coord_key(part.coords[0]))
            protected_keys.add(_coord_key(part.coords[-1]))

    prepared_with_source: list[tuple[Mapping[str, Any], Any, Any]] = []
    maximum_displacement = 0.0
    smoothed_minor_count = 0
    protected_anchor_count = len(protected_keys)
    valley_surface = None
    if terrain_surface is not None:
        valley_surface = np.asarray(terrain_surface, dtype=np.float64) - gaussian_blur_array(
            np.asarray(terrain_surface, dtype=np.float64), 8.0
        )
    for row, geometry in selected:
        if row["source_kind"] != "minor":
            prepared_with_source.append((row, geometry, geometry))
            continue
        parts: list[LineString] = []
        for part in _line_parts(geometry):
            smoothed, displacement, _ = topology_locked_smoothing(
                part,
                protected_keys,
                confluence_keys=confluence_keys,
                valley_surface=valley_surface,
                bounds=bounds,
            )
            parts.append(smoothed)
            maximum_displacement = max(maximum_displacement, displacement)
            smoothed_minor_count += int(displacement > 0.0)
        display_geometry = parts[0] if len(parts) == 1 else MultiLineString(parts)
        prepared_with_source.append((row, geometry, display_geometry))

    # A display curve must not create a new crossing between registered
    # routes.  If a fitted minor would do so, retain that route's local source
    # geometry while leaving the rest of the network improved.
    prepared: list[tuple[Mapping[str, Any], Any]] = []
    accepted_sources: list[Any] = []
    accepted_displays: list[Any] = []
    new_intersection_fallback_count = 0
    for row, source_geometry, display_geometry in prepared_with_source:
        conflict = any(
            float(source_geometry.distance(previous_source)) > 0.002
            and display_geometry.intersects(previous_display)
            for previous_source, previous_display in zip(accepted_sources, accepted_displays)
        )
        if conflict and row["source_kind"] == "minor":
            display_geometry = source_geometry
            new_intersection_fallback_count += 1
        prepared.append((row, display_geometry))
        accepted_sources.append(source_geometry)
        accepted_displays.append(display_geometry)

    maximum_displacement = max(
        (
            float(shapely.hausdorff_distance(source_geometry, display_geometry))
            for (_, source_geometry, _), (_, display_geometry) in zip(prepared_with_source, prepared)
        ),
        default=0.0,
    )

    transparent = Image.new("RGBA", image.size, (0, 0, 0, 0))
    land_layer = transparent.copy()
    water_layer = transparent.copy()
    land_draw = ImageDraw.Draw(land_layer, "RGBA")
    water_draw = ImageDraw.Draw(water_layer, "RGBA")
    prepared.sort(key=lambda item: {"tier1": 0, "tier2": 1, "major": 2, "titan": 3}.get(str(item[0]["route_class"]), 0))
    for row, geometry in prepared:
        clipped = geometry.intersection(extent)
        route_class = str(row["route_class"])
        core_width = _route_width(route_class)
        seasonal = str(row.get("persistence") or "").lower() == "seasonal"
        for part in _line_parts(clipped):
            points = _world_to_work(part.coords, bounds)
            if seasonal:
                _draw_dashed_line(land_draw, points, (37, 94, 115, 215), core_width + 2 * OVERSAMPLE, 18 * OVERSAMPLE, 11 * OVERSAMPLE)
                _draw_dashed_line(land_draw, points, (85, 158, 176, 235), core_width, 18 * OVERSAMPLE, 11 * OVERSAMPLE)
                _draw_dashed_line(water_draw, points, (27, 91, 116, 205), max(2 * OVERSAMPLE, core_width // 3), 18 * OVERSAMPLE, 11 * OVERSAMPLE)
            else:
                _draw_round_line(land_draw, points, (31, 82, 105, 225), core_width + 2 * OVERSAMPLE)
                _draw_round_line(land_draw, points, (51, 139, 169, 248), core_width)
                _draw_round_line(water_draw, points, (24, 91, 119, 205), max(2 * OVERSAMPLE, core_width // 3))

    if open_water_mask is None:
        image.alpha_composite(land_layer)
    else:
        water_mask = _soft_mask(np.asarray(open_water_mask, dtype=np.float32), 0.0)
        land_mask = water_mask.point(lambda value: 255 - value)
        image.alpha_composite(Image.composite(land_layer, transparent, land_mask))
        image.alpha_composite(Image.composite(water_layer, transparent, water_mask))

    interior_endpoints: list[list[float]] = []
    longest_visible_part: LineString | None = None
    for _, geometry in prepared:
        for part in _line_parts(geometry.intersection(extent)):
            if longest_visible_part is None or float(part.length) > float(longest_visible_part.length):
                longest_visible_part = part
            for coordinate in (part.coords[0], part.coords[-1]):
                x_km, y_km = float(coordinate[0]), float(coordinate[1])
                if bounds[0] + 0.06 < x_km < bounds[2] - 0.06 and bounds[1] + 0.06 < y_km < bounds[3] - 0.06:
                    interior_endpoints.append([x_km, y_km])
    principal_midpoint = None
    if longest_visible_part is not None:
        midpoint = longest_visible_part.interpolate(0.52, normalized=True)
        principal_midpoint = [float(midpoint.x), float(midpoint.y)]

    return {
        "accepted_route_count": len(prepared),
        "major_route_count": sum(row["source_kind"] == "major" for row, _ in prepared),
        "minor_route_count": sum(row["source_kind"] == "minor" for row, _ in prepared),
        "minor_smoothed_count": smoothed_minor_count,
        "minor_maximum_display_displacement_km": maximum_displacement,
        "minor_smoothing_method": "TOPOLOGY_LOCKED_TERRAIN_GUIDED_NONPERIODIC_CORRIDOR_FIT",
        "new_intersection_fallback_count": new_intersection_fallback_count,
        "visible_source_feature_ids": sorted(str(row["feature_id"]) for row, _ in selected),
        "display_feature_ids": sorted(str(row["feature_id"]) for row, _ in prepared),
        "visible_source_display_feature_set_equal": {
            str(row["feature_id"]) for row, _ in selected
        } == {
            str(row["feature_id"]) for row, _ in prepared
        },
        "major_registered_planforms_unchanged": True,
        "protected_endpoint_or_confluence_anchor_count": protected_anchor_count,
        "seasonal_route_count": sum(str(row.get("persistence") or "").lower() == "seasonal" for row, _ in prepared),
        "interior_route_endpoints_km": interior_endpoints,
        "principal_visible_route_midpoint_km": principal_midpoint,
        "registered_endpoint_annotations": endpoint_annotations,
        "generated_drainage_drawn": False,
    }


def _draw_polygon_water(
    image: Image.Image,
    geometries: Sequence[Any],
    bounds: tuple[float, float, float, float],
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    edge_blur_px: float = 0.0,
) -> None:
    extent = box(*bounds)
    mask = Image.new("L", image.size, 0)
    draw_mask = ImageDraw.Draw(mask)
    for geometry in geometries:
        if geometry is None or geometry.is_empty or not geometry.intersects(extent):
            continue
        display_geometry = cartographic_water_polygon(geometry)
        for polygon in _polygon_parts(display_geometry.intersection(extent)):
            exterior = _world_to_work(polygon.exterior.coords, bounds)
            draw_mask.polygon(exterior, fill=255)
            for ring in polygon.interiors:
                draw_mask.polygon(_world_to_work(ring.coords, bounds), fill=0)
    if edge_blur_px > 0.0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=edge_blur_px))
    overlay = Image.new("RGBA", image.size, fill)
    image.alpha_composite(Image.composite(overlay, Image.new("RGBA", image.size, (0, 0, 0, 0)), mask))
    if outline is not None:
        draw = ImageDraw.Draw(image, "RGBA")
        for geometry in geometries:
            if geometry is None or geometry.is_empty or not geometry.intersects(extent):
                continue
            display_geometry = cartographic_water_polygon(geometry)
            for polygon in _polygon_parts(display_geometry.intersection(extent)):
                draw.line(_world_to_work(polygon.exterior.coords, bounds), fill=outline, width=2 * OVERSAMPLE, joint="curve")


def cartographic_water_polygon(geometry: Any) -> Any:
    """Generalise a vectorised 100 m raster shoreline for display only."""

    parts: list[Polygon] = []
    for polygon in _polygon_parts(geometry):
        coordinates = np.asarray(polygon.exterior.coords, dtype=np.float64)
        differences = np.diff(coordinates, axis=0)
        if differences.size == 0:
            parts.append(polygon)
            continue
        axis_aligned = np.isclose(differences[:, 0], 0.0, atol=1e-8) | np.isclose(
            differences[:, 1], 0.0, atol=1e-8
        )
        step_length = np.maximum(np.abs(differences[:, 0]), np.abs(differences[:, 1]))
        source_grid_steps = np.isclose(step_length, 0.1, atol=1e-6)
        if float(np.mean(axis_aligned)) < 0.7 or float(np.mean(source_grid_steps)) < 0.45:
            parts.append(polygon)
            continue
        candidate = polygon.simplify(math.sqrt(0.1 ** 2 / 2.0) + 1e-6, preserve_topology=True)
        candidate = candidate.buffer(0.015, quad_segs=4, join_style="round").buffer(
            -0.015, quad_segs=4, join_style="round"
        )
        area_ratio = float(candidate.area / polygon.area) if polygon.area > 0.0 else 1.0
        if candidate.is_empty or not candidate.is_valid or not 0.97 <= area_ratio <= 1.03:
            parts.append(polygon)
        else:
            parts.extend(_polygon_parts(candidate))
    return shapely.union_all(parts) if len(parts) > 1 else parts[0] if parts else geometry


def _water_geometries(vectors: s6c.VectorStack, bounds: tuple[float, float, float, float]) -> tuple[list[Any], list[Any]]:
    extent = box(*bounds)
    permanent = [geometry for geometry in vectors.permanent_lake_geoms if geometry.intersects(extent)]
    permanent.extend(geometry for geometry in vectors.managed_special_geoms if geometry.intersects(extent))
    seasonal = [geometry for geometry in vectors.seasonal_lake_geoms if geometry.intersects(extent)]
    return permanent, seasonal


def _load_locator_mask() -> Image.Image:
    path = Path(source_path("obsidian_sea_mask_100m"))
    with rasterio.open(path) as dataset:
        sea = dataset.read(out_shape=(1, 186, 220), resampling=Resampling.average)[0].astype(np.float32)
    if float(np.nanmax(sea)) > 1.0:
        sea /= float(np.nanmax(sea))
    land = sea < 0.5
    rgb = np.zeros((186, 220, 3), dtype=np.uint8)
    rgb[:] = np.array([178, 204, 213], dtype=np.uint8)
    rgb[land] = np.array([173, 169, 143], dtype=np.uint8)
    return Image.fromarray(rgb, mode="RGB").resize((220, 186), PIL_LANCZOS)


def _site_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    query = """
    SELECT r.settlement_id, r.official_x_km, r.official_y_km, r.zarr_index,
           r.array_digest, r.conditioning_delta_max_abs_m, r.disposition,
           s.settlement_name, s.barony_id, s.stage6b_functional_tier,
           a.owner_haus_id, a.horizontal_uncertainty_radius_km,
           a.coordinate_precision_basis, a.effective_vertical_domain,
           a.terrain_elevation_m, a.local_relief_m, a.wetland_fraction,
           a.serenakrone_water_fraction, p.barony_name, p.county_name,
           p.duchy_name, p.climate_descriptor, p.leading_formation_name,
           p.secondary_formation_name, p.terrain_descriptor
    FROM stage6c5r_site_physical_context r
    JOIN settlement s USING(settlement_id)
    JOIN stage6c_site_assessment a USING(settlement_id)
    LEFT JOIN province p ON p.barony_id=s.barony_id
    ORDER BY r.settlement_id
    """
    return [dict(row) for row in connection.execute(query)]


def _route_rows(connection: sqlite3.Connection, settlement_id: str) -> list[dict[str, Any]]:
    query = """
    SELECT feature_id, source_kind, route_class, persistence, receiver_id,
           boundary_inflow, boundary_outflow, physical_route_accepted, route_status
    FROM stage6c5r_route_context
    WHERE settlement_id=?
    ORDER BY source_kind, feature_id, part_id
    """
    return [dict(row) for row in connection.execute(query, (settlement_id,))]


def _window_bounds(settlement_id: str) -> tuple[float, float, float, float]:
    checkpoint = json.loads((SOURCE_DIR / "checkpoints" / f"{settlement_id}.json").read_text(encoding="utf-8"))
    row0, col0, height, width = checkpoint["window_parent"]
    return col0 * 0.1, row0 * 0.1, (col0 + width) * 0.1, (row0 + height) * 0.1


def _title(metadata: Mapping[str, Any]) -> tuple[str, str]:
    haus = HAUS_DISPLAY.get(str(metadata["owner_haus_id"]), str(metadata["owner_haus_id"]).replace("_", " ").title())
    if metadata.get("settlement_name"):
        return f"{metadata['settlement_name']} — {haus}", "Haus capital-site candidate"
    if str(metadata.get("owner_haus_id")) == "SERENAKRONE":
        return f"{haus} capital-site candidate", "Surface lagoon capital-site physical context"
    return f"{haus} capital-site candidate", "Stage 6C.5R Haus principal-site physical context"


def _draw_site_marker(map_image: Image.Image, metadata: Mapping[str, Any], bounds: tuple[float, float, float, float]) -> None:
    xmin, ymin, xmax, ymax = bounds
    x = int(round((float(metadata["official_x_km"]) - xmin) / (xmax - xmin) * MAP_PX))
    y = int(round((float(metadata["official_y_km"]) - ymin) / (ymax - ymin) * MAP_PX))
    draw = ImageDraw.Draw(map_image, "RGBA")
    radius = 13
    outer = [(x, y - radius - 3), (x + radius + 3, y), (x, y + radius + 3), (x - radius - 3, y)]
    middle = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)]
    inner = [(x, y - 7), (x + 7, y), (x, y + 7), (x - 7, y)]
    draw.polygon(outer, fill=(255, 255, 250, 245))
    draw.polygon(middle, fill=(47, 43, 37, 250))
    sampled = map_image.getpixel((min(max(x, 0), MAP_PX - 1), min(max(y, 0), MAP_PX - 1)))
    draw.polygon(inner, fill=(*sampled[:3], 255))
    label = HAUS_DISPLAY.get(str(metadata["owner_haus_id"]), str(metadata["owner_haus_id"]).title())
    if metadata.get("settlement_name"):
        label = str(metadata["settlement_name"])
    text_box = draw.textbbox((0, 0), label, font=LABEL_FONT, stroke_width=5)
    text_width = int(text_box[2] - text_box[0])
    text_height = int(text_box[3] - text_box[1])
    candidates = (
        (x + 24, y - text_height - 24),
        (x + 24, y + 18),
        (x - text_width - 24, y - text_height - 24),
        (x - text_width - 24, y + 18),
    )
    pixels = np.asarray(map_image.convert("RGB"))
    blue_feature = (pixels[..., 2].astype(np.int16) - pixels[..., 0].astype(np.int16) > 18) & (
        pixels[..., 2] >= pixels[..., 1] - 18
    )
    scored: list[tuple[float, int, int]] = []
    for preference, (candidate_x, candidate_y) in enumerate(candidates):
        left = max(0, candidate_x - 8)
        top = max(0, candidate_y - 8)
        right = min(MAP_PX, candidate_x + text_width + 8)
        bottom = min(MAP_PX, candidate_y + text_height + 8)
        clipped_area = max(0, text_width * text_height - max(0, right - left) * max(0, bottom - top))
        feature_overlap = int(np.count_nonzero(blue_feature[top:bottom, left:right]))
        scored.append((feature_overlap * 20.0 + clipped_area * 100.0 + preference, candidate_x, candidate_y))
    _, label_x, label_y = min(scored)
    label_x = max(12, min(MAP_PX - text_width - 12, label_x))
    label_y = max(12, min(MAP_PX - text_height - 12, label_y))
    draw.text((label_x, label_y), label, font=LABEL_FONT, fill=(30, 28, 24, 255), stroke_width=5, stroke_fill=(247, 245, 235, 235))


def _draw_scale_and_north(map_image: Image.Image) -> None:
    draw = ImageDraw.Draw(map_image, "RGBA")
    x0, y0 = 45, MAP_PX - 58
    segment = int(round(MAP_PX / 6.0))
    draw.rounded_rectangle((25, MAP_PX - 100, x0 + 2 * segment + 35, MAP_PX - 20), radius=8, fill=(248, 246, 236, 205))
    for index, colour in enumerate(((37, 36, 32, 255), (246, 244, 233, 255))):
        draw.rectangle((x0 + index * segment, y0, x0 + (index + 1) * segment, y0 + 13), fill=colour, outline=(37, 36, 32, 255), width=2)
    draw.text((x0 - 4, y0 + 17), "0", font=SMALL_FONT, fill=(30, 28, 24, 255))
    draw.text((x0 + segment - 18, y0 + 17), "500 m", font=SMALL_FONT, fill=(30, 28, 24, 255))
    draw.text((x0 + 2 * segment - 19, y0 + 17), "1 km", font=SMALL_FONT, fill=(30, 28, 24, 255))

    nx, ny = MAP_PX - 58, 62
    draw.text((nx - 7, ny - 42), "N", font=STATUS_FONT, fill=(30, 28, 24, 255), stroke_width=3, stroke_fill=(248, 246, 236, 230))
    draw.polygon([(nx, ny - 8), (nx - 12, ny + 22), (nx, ny + 15), (nx + 12, ny + 22)], fill=(35, 34, 31, 245))
    draw.line((nx, ny - 7, nx, ny + 42), fill=(35, 34, 31, 245), width=3)


def _draw_locator(canvas: Image.Image, locator: Image.Image, metadata: Mapping[str, Any], x: int, y: int) -> None:
    canvas.paste(locator, (x, y))
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle((x, y, x + locator.width - 1, y + locator.height - 1), outline=(78, 74, 66, 180), width=2)
    px = x + int(round(float(metadata["official_x_km"]) / 2200.0 * locator.width))
    py = y + int(round(float(metadata["official_y_km"]) / 1860.0 * locator.height))
    draw.polygon([(px, py - 7), (px + 7, py), (px, py + 7), (px - 7, py)], fill=(178, 36, 39, 255), outline=(255, 255, 248, 255))
    draw.text((x, y - 22), "Position relative to the Obsidian Sea", font=SMALL_FONT, fill=(62, 58, 51, 255))


def _draw_special_context_labels(
    image: Image.Image,
    metadata: Mapping[str, Any],
    bounds: tuple[float, float, float, float],
    route_metrics: Mapping[str, Any],
) -> None:
    """Explain specialist surface-water symbols that would otherwise mislead."""

    draw = ImageDraw.Draw(image, "RGBA")
    xmin, ymin, xmax, ymax = bounds

    def map_point(coordinate: Sequence[float]) -> tuple[int, int]:
        return (
            int(round((float(coordinate[0]) - xmin) / (xmax - xmin) * MAP_PX)),
            int(round((float(coordinate[1]) - ymin) / (ymax - ymin) * MAP_PX)),
        )

    owner = str(metadata.get("owner_haus_id") or "")
    if owner == "STILLKLINGE":
        endpoints = route_metrics.get("interior_route_endpoints_km") or []
        if endpoints:
            official = (float(metadata["official_x_km"]), float(metadata["official_y_km"]))
            coordinate = min(
                endpoints,
                key=lambda item: (float(item[0]) - official[0]) ** 2 + (float(item[1]) - official[1]) ** 2,
            )
            x, y = map_point(coordinate)
            draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(246, 244, 233, 245), outline=(29, 92, 120, 245), width=3)
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(43, 131, 161, 255))
            label_x = min(max(12, x + 15), MAP_PX - 170)
            label_y = min(max(10, y - 23), MAP_PX - 30)
            draw.text(
                (label_x, label_y),
                "surface resurgence",
                font=CONTEXT_FONT,
                fill=(25, 76, 99, 255),
                stroke_width=4,
                stroke_fill=(247, 245, 235, 235),
            )
    elif owner == "SERENAKRONE":
        midpoint = route_metrics.get("principal_visible_route_midpoint_km")
        if midpoint:
            x, y = map_point(midpoint)
            label = "principal lagoon channel"
            box_width = draw.textbbox((0, 0), label, font=CONTEXT_FONT, stroke_width=4)[2]
            label_x = x - int(box_width) - 18 if x > MAP_PX * 0.60 else x + 18
            label_x = min(max(12, label_x), MAP_PX - int(box_width) - 12)
            label_y = min(max(10, y - 20), MAP_PX - 30)
            draw.text(
                (label_x, label_y),
                label,
                font=CONTEXT_FONT,
                fill=(24, 77, 101, 235),
                stroke_width=4,
                stroke_fill=(235, 240, 229, 215),
            )

    if owner in {"BUCHHAIN", "WIEDERGEBORENE_FLAMME"}:
        annotations = route_metrics.get("registered_endpoint_annotations") or []
        seen_coordinates: set[tuple[int, int]] = set()
        drawn = 0
        for annotation in annotations:
            if annotation.get("label") == "registered route entry":
                continue
            coordinate = annotation.get("coordinate_km")
            if not coordinate:
                continue
            key = _coord_key(coordinate)
            if key in seen_coordinates:
                continue
            seen_coordinates.add(key)
            x, y = map_point(coordinate)
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(244, 243, 233, 235), outline=(35, 105, 132, 245), width=2)
            label = str(annotation.get("label") or "registered network endpoint")
            width = draw.textbbox((0, 0), label, font=SMALL_FONT, stroke_width=3)[2]
            label_x = x + 11 if x + width + 20 < MAP_PX else x - width - 11
            label_y = min(max(8, y - 16 + drawn * 18), MAP_PX - 26)
            draw.text(
                (label_x, label_y),
                label,
                font=SMALL_FONT,
                fill=(28, 84, 108, 245),
                stroke_width=3,
                stroke_fill=(247, 245, 235, 225),
            )
            drawn += 1
            if drawn >= 2:
                break


def render_site(
    metadata: Mapping[str, Any],
    group: zarr.Group,
    route_rows: Sequence[Mapping[str, Any]],
    major_by_id: Mapping[str, Any],
    minor_by_id: Mapping[str, Any],
    vectors: s6c.VectorStack,
    locator: Image.Image,
    output_dir: Path,
    maps_subdir: str,
) -> dict[str, Any]:
    settlement_id = str(metadata["settlement_id"])
    index = int(metadata["zarr_index"])
    base = np.asarray(group["base_broad_elevation_m"][index], dtype=np.float64)
    conditioned = np.asarray(group["conditioned_elevation_m"][index], dtype=np.float64)
    arrays = {
        "sea": np.asarray(group["sea_mask_parent_projected"][index], dtype=np.float32),
        "wetland": np.asarray(group["wetland_mask_parent_projected"][index], dtype=np.float32),
        "lagoon": np.asarray(group["serenakrone_water_parent_projected"][index], dtype=np.float32),
    }
    display_sea = natural_water_display_mask(arrays["sea"])
    display_lagoon = natural_water_display_mask(arrays["lagoon"])
    display_open_water = (display_sea >= 0.5) | (display_lagoon >= 0.5)
    elevation, parent = display_elevation(base, conditioned)
    unconditioned_display_elevation = pchip_surface(parent)
    relief_surface = gaussian_blur_array(elevation, TERRAIN_DISPLAY_SMOOTHING_SIGMA_CELLS)
    if float(np.min(elevation)) < float(np.min(parent)) - float(metadata["conditioning_delta_max_abs_m"]) - 1e-5:
        raise RuntimeError(f"Display terrain undershot source envelope: {settlement_id}")
    if float(np.max(elevation)) > float(np.max(parent)) + float(metadata["conditioning_delta_max_abs_m"]) + 1e-5:
        raise RuntimeError(f"Display terrain overshot source envelope: {settlement_id}")

    rgb = terrain_rgb(elevation, metadata, relief_surface)
    map_work = Image.fromarray(rgb, mode="RGB").resize((WORK_PX, WORK_PX), PIL_BICUBIC)
    wetland_mean = float(np.mean(arrays["wetland"]))
    wetland_alpha = 112 if wetland_mean >= 0.95 else 82
    map_work = _blend_colour(map_work, arrays["wetland"], (66, 130, 126), wetland_alpha, 1.5)
    map_work = _blend_colour(map_work, display_sea, (66, 137, 164), 235, 0.0)
    map_work = _blend_colour(map_work, display_lagoon, (70, 149, 170), 220, 0.0)
    map_work = map_work.convert("RGBA")
    bounds = _window_bounds(settlement_id)

    interval = nice_contour_interval(elevation)
    _draw_contours(map_work, relief_surface, interval, display_open_water)
    permanent, seasonal = _water_geometries(vectors, bounds)
    _draw_polygon_water(map_work, permanent, bounds, (65, 140, 165, 225), (38, 105, 132, 220))
    _draw_polygon_water(
        map_work,
        seasonal,
        bounds,
        (79, 145, 153, 68),
        None,
        edge_blur_px=25 * OVERSAMPLE,
    )
    route_metrics = _draw_routes(
        map_work,
        bounds,
        route_rows,
        major_by_id,
        minor_by_id,
        display_open_water.astype(np.float32),
        terrain_surface=unconditioned_display_elevation,
    )
    map_image = map_work.convert("RGB").resize((MAP_PX, MAP_PX), PIL_LANCZOS).convert("RGBA")
    _draw_special_context_labels(map_image, metadata, bounds, route_metrics)
    _draw_site_marker(map_image, metadata, bounds)
    _draw_scale_and_north(map_image)

    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (242, 240, 230))
    draw = ImageDraw.Draw(canvas, "RGBA")
    title, subtitle = _title(metadata)
    draw.text((70, 34), title, font=TITLE_FONT, fill=(39, 36, 30, 255))
    if metadata.get("barony_name"):
        province = str(metadata["barony_name"])
    elif metadata.get("barony_id") is not None:
        province = f"Barony {metadata['barony_id']}"
        if metadata.get("county_name"):
            province += f" · {metadata['county_name']}"
    else:
        province = "surface / lagoon interface"
    draw.text((72, 90), f"{subtitle} · {province} · 3 km × 3 km", font=SUBTITLE_FONT, fill=(69, 64, 56, 255))
    draw.text((72, 126), "WORKING PROPOSAL · REVIEW ONLY · NOT CANON", font=STATUS_FONT, fill=(145, 47, 43, 255))
    canvas.paste(map_image.convert("RGB"), (MAP_LEFT, MAP_TOP))
    draw.rectangle((MAP_LEFT, MAP_TOP, MAP_LEFT + MAP_PX, MAP_TOP + MAP_PX), outline=(62, 58, 50, 210), width=2)

    footer_y = MAP_TOP + MAP_PX + 25
    minimum, maximum = float(np.nanmin(elevation)), float(np.nanmax(elevation))
    interval_text = "no contours (local relief <1 m)" if interval is None else f"{interval:g} m contours"
    draw.text((72, footer_y), f"Elevation {minimum:,.1f}–{maximum:,.1f} m · {interval_text} · multidirectional relief shading ×2", font=BODY_FONT, fill=(53, 49, 43, 255))
    draw.text((72, footer_y + 31), "Terrain is a continuous display interpretation of the active 100 m authority; no procedural microrelief was added.", font=SMALL_FONT, fill=(76, 70, 61, 255))
    draw.text((72, footer_y + 55), "Only accepted registered waterways are shown. Generated runoff is hidden; line weight denotes hierarchy, not observed width.", font=SMALL_FONT, fill=(76, 70, 61, 255))
    uncertainty = float(metadata.get("horizontal_uncertainty_radius_km") or 0.0)
    position_note = (
        f"Representative coordinate; horizontal uncertainty approximately ±{uncertainty * 1000:,.0f} m."
        if uncertainty >= 0.1
        else "Hollow diamond marks the retained review coordinate; it does not imply a final built footprint."
    )
    draw.text((72, footer_y + 79), position_note, font=SMALL_FONT, fill=(76, 70, 61, 255))
    note_y = footer_y + 103
    if seasonal:
        draw.text((72, note_y), "Seasonal water is a feathered possible extent, not a fixed shoreline.", font=SMALL_FONT, fill=(48, 105, 111, 255))
        note_y += 24
    if int(route_metrics.get("seasonal_route_count") or 0) > 0:
        draw.text((72, note_y), "Dashed blue line = accepted seasonal waterway.", font=SMALL_FONT, fill=(48, 105, 111, 255))
        note_y += 24
    if wetland_mean >= 0.95:
        draw.text((72, note_y), "Core wetland throughout this lens.", font=SMALL_FONT, fill=(45, 102, 98, 255))
        note_y += 24
    if str(metadata.get("owner_haus_id")) == "SERENAKRONE" and float(metadata.get("serenakrone_water_fraction") or 0.0) > 0.0:
        draw.text((72, note_y), "The retained coordinate is classified as a surface lagoon site.", font=SMALL_FONT, fill=(37, 102, 126, 255))
        note_y += 24
        draw.text((72, note_y), "The thin dark axis is the accepted principal lagoon channel, not a border.", font=SMALL_FONT, fill=(37, 102, 126, 255))
        note_y += 24
    if str(metadata.get("owner_haus_id")) == "STILLKLINGE" and int(route_metrics.get("minor_route_count") or 0) == 0:
        draw.text((72, note_y), "The repaired supporting minor hydroscape does not intersect this 3 km lens.", font=SMALL_FONT, fill=(37, 102, 126, 255))
        note_y += 24
    if str(metadata.get("owner_haus_id")) in {"BUCHHAIN", "WIEDERGEBORENE_FLAMME"} and route_metrics.get("registered_endpoint_annotations"):
        draw.text((72, note_y), "Blue-ring markers identify registered network endpoints; unaccepted continuations are not inferred.", font=SMALL_FONT, fill=(37, 102, 126, 255))
        note_y += 24
    vertical = str(metadata.get("effective_vertical_domain") or "")
    if any(token in vertical.upper() for token in ("CAVERN", "SUBMERGED", "UNDERWATER", "LAGOON")):
        draw.text((72, note_y), "This is surface/interface context; specialist three-dimensional geography remains a separate later pass.", font=SMALL_FONT, fill=(106, 75, 49, 255))
    draw.text((72, CANVAS_H - 28), f"Reference {settlement_id} · {METHOD}", font=SMALL_FONT, fill=(103, 96, 84, 255))
    _draw_locator(canvas, locator, metadata, CANVAS_W - 292, footer_y + 5)

    maps_dir = output_dir / maps_subdir
    maps_dir.mkdir(parents=True, exist_ok=True)
    output = maps_dir / f"{settlement_id}.png"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    canvas.save(temporary, format="PNG", optimize=True)
    os.replace(temporary, output)
    return {
        "settlement_id": settlement_id,
        "title": title,
        "official_coordinate_km": [float(metadata["official_x_km"]), float(metadata["official_y_km"])],
        "source_array_digest": metadata["array_digest"],
        "output_relative_path": output.relative_to(output_dir).as_posix(),
        "output_sha256": sha256_file(output),
        "output_size_bytes": output.stat().st_size,
        "display_elevation_min_m": minimum,
        "display_elevation_max_m": maximum,
        "contour_interval_m": interval,
        "terrain_interpolation": "SEPARABLE_SHAPE_PRESERVING_CUBIC_FROM_100M_PARENT_MEANS_PLUS_EXACT_VALIDATED_CONDITIONING_RESIDUAL",
        "terrain_source_envelope_pass": True,
        "route_metrics": route_metrics,
        "site_marker_coordinate_preserved": True,
        "north_up_y_increases_south_pass": True,
        "canon_status": CANON_STATUS,
    }


def self_test() -> None:
    monotone = np.array([0.0, 1.0, 3.0, 4.0], dtype=np.float64)
    refined = pchip_resample_1d(monotone, 10)
    assert float(np.min(refined)) >= 0.0 and float(np.max(refined)) <= 4.0
    assert np.all(np.diff(refined) >= -1e-12)
    right_angle = LineString([(0.0, 0.0), (0.1, 0.0), (0.1, 0.1)])
    smoothed, displacement, _ = topology_locked_smoothing(
        right_angle,
        {_coord_key(right_angle.coords[0]), _coord_key(right_angle.coords[-1])},
    )
    assert _coord_key(smoothed.coords[0]) == _coord_key(right_angle.coords[0])
    assert _coord_key(smoothed.coords[-1]) == _coord_key(right_angle.coords[-1])
    assert displacement <= MINOR_MAX_DISPLACEMENT_KM + 1e-9
    staircase_parent = np.zeros((30, 30), dtype=np.uint8)
    for row in range(8, 30):
        staircase_parent[row, max(0, 30 - (row - 7)) :] = 1
    staircase = np.repeat(np.repeat(staircase_parent, 10, axis=0), 10, axis=1)
    natural = natural_water_display_mask(staircase)
    assert natural.shape == staircase.shape
    assert int(np.count_nonzero(natural >= 0.5)) == int(np.count_nonzero(staircase))
    stair_polygon = Polygon(
        [(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.2, 0.1),
         (0.2, 0.2), (0.3, 0.2), (0.3, 0.3), (0.0, 0.3), (0.0, 0.0)]
    )
    generalised = cartographic_water_polygon(stair_polygon)
    assert generalised.is_valid and not generalised.is_empty
    assert 0.97 <= float(generalised.area / stair_polygon.area) <= 1.03
    assert float(generalised.hausdorff_distance(stair_polygon)) <= 0.1
    relief_fixture = np.arange(900, dtype=np.float64).reshape(30, 30)
    relief_blurred = gaussian_blur_array(relief_fixture, 2.0)
    assert relief_blurred.shape == relief_fixture.shape and np.isfinite(relief_blurred).all()
    assert _world_to_work([(1.0, 1.0), (1.0, 2.0)], (0.0, 0.0, 3.0, 3.0))[0][1] < _world_to_work([(1.0, 2.0)], (0.0, 0.0, 3.0, 3.0))[0][1]


def run(output_dir: Path, selection: Sequence[str] | None) -> dict[str, Any]:
    self_test()
    output_dir.mkdir(parents=True, exist_ok=True)
    is_full_batch = selection is None
    maps_subdir = "presentation_maps" if is_full_batch else "presentation_maps_partial"
    connection = sqlite3.connect(f"file:{SOURCE_DB.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Source Stage 6C.5R database failed integrity check")
        sites = _site_rows(connection)
        if len(sites) != 19:
            raise RuntimeError(f"Expected 19 completed FT0 sites, found {len(sites)}")
        if selection:
            requested = set(selection)
            sites = [site for site in sites if site["settlement_id"] in requested]
            missing = requested - {site["settlement_id"] for site in sites}
            if missing:
                raise KeyError(f"Unknown Stage 6C.5R sites: {sorted(missing)}")

        group = zarr.open_group(str(SOURCE_ZARR), mode="r")
        vectors = s6c.VectorStack("reference")
        major_by_id = {
            str(properties.get("route_id")): geometry
            for geometry, properties in zip(vectors.major_geoms, vectors.major_props)
        }
        minor_by_id = {
            str(properties.get("minor_id")): geometry
            for geometry, properties in zip(vectors.minor_geoms, vectors.minor_props)
        }
        locator = _load_locator_mask()
        results = []
        for position, metadata in enumerate(sites, 1):
            print(f"CAPITAL_MAP {position}/{len(sites)} {metadata['settlement_id']}", flush=True)
            results.append(
                render_site(
                    metadata,
                    group,
                    _route_rows(connection, str(metadata["settlement_id"])),
                    major_by_id,
                    minor_by_id,
                    vectors,
                    locator,
                    output_dir,
                    maps_subdir,
                )
            )
    finally:
        connection.close()

    manifest = {
        "schema": "diadem.stage6c5r-natural-capital-maps.v1",
        "created_utc": utc_now(),
        "method": METHOD,
        "canon_status": CANON_STATUS,
        "batch_scope": "FULL_19_SITE_BATCH" if is_full_batch else "PARTIAL_DEVELOPMENT_RENDER",
        "source_stage6c5r_directory": str(SOURCE_DIR),
        "source_analytical_files_modified": False,
        "diagnostic_review_maps_modified": False,
        "renderer_parameters": {
            "map_pixels": MAP_PX,
            "oversample_factor": OVERSAMPLE,
            "terrain_authority_resolution_m": 100,
            "analytical_lens_spacing_m": 10,
            "terrain_relief_display_smoothing_sigma_m": TERRAIN_DISPLAY_SMOOTHING_SIGMA_CELLS * 10.0,
            "complex_categorical_water_fallback_smoothing_radius_m": LAGOON_DISPLAY_SMOOTHING_RADIUS_CELLS * 10.0,
            "edge_connected_water_display_method": "AREA_PRESERVING_REGULARISED_CONTINUOUS_SHORELINE_FROM_100M_PARENT",
            "grid_derived_polygon_shoreline_generalisation_limit_m": math.sqrt(0.1 ** 2 / 2.0) * 1000.0,
            "seasonal_water_display": "FEATHERED_POSSIBLE_EXTENT_WITHOUT_FIXED_SHORELINE",
            "minor_display_smoothing_max_displacement_m": MINOR_MAX_DISPLACEMENT_KM * 1000.0,
            "minor_display_fit": "LOCAL_LENS_PLUS_80M_HALO_TERRAIN_GUIDED_NONPERIODIC_20M_STATIONS_5M_LATERAL_STATES",
            "minor_terrain_guided_max_offset_m": MINOR_TERRAIN_GUIDED_OFFSET_KM * 1000.0,
            "minor_anchor_taper_distance_m": 160,
            "minor_continuous_corridor_internal_limit_m": (MINOR_MAX_DISPLACEMENT_KM - 0.001) * 1000.0,
            "minimum_closed_contour_perimeter_m": MINIMUM_CLOSED_CONTOUR_PERIMETER_KM * 1000.0,
            "minimum_closed_contour_area_km2": MINIMUM_CLOSED_CONTOUR_AREA_KM2,
            "generated_drainage_visible": False,
            "relief_vertical_exaggeration": 2.0,
            "lossless_output": "PNG",
        },
        "source_vector_hashes": {
            "active_major": s6c.SOURCES["active_major"]["sha256"],
            "d3_feeder_raw": s6c.SOURCES["d3_feeder_raw"]["sha256"],
            "d3_feeder_enriched": s6c.SOURCES["d3_feeder_enriched"]["sha256"],
            "stillklinge_support": s6c.SOURCES["stillklinge_support"]["sha256"],
            "coastline": s6c.SOURCES["coastline"]["sha256"],
        },
        "site_count": len(results),
        "sites": results,
    }
    manifest_name = "PRESENTATION_MAP_MANIFEST.json" if is_full_batch else "PRESENTATION_MAP_MANIFEST_PARTIAL.json"
    atomic_json(output_dir / manifest_name, manifest)
    validation_checks = {
        "one_lossless_png_per_rendered_site": len(results) == len({item["output_relative_path"] for item in results}),
        "all_output_hashes_reverified": all(
            sha256_file(output_dir / item["output_relative_path"]) == item["output_sha256"]
            for item in results
        ),
        "all_site_markers_preserved": all(bool(item["site_marker_coordinate_preserved"]) for item in results),
        "all_maps_north_up": all(bool(item["north_up_y_increases_south_pass"]) for item in results),
        "all_terrain_source_envelopes_pass": all(bool(item["terrain_source_envelope_pass"]) for item in results),
        "minor_display_displacement_within_50m": all(
            float(item["route_metrics"]["minor_maximum_display_displacement_km"])
            <= MINOR_MAX_DISPLACEMENT_KM + 1e-9
            for item in results
        ),
        "generated_drainage_hidden": all(
            not bool(item["route_metrics"]["generated_drainage_drawn"])
            for item in results
        ),
        "visible_source_display_route_sets_equal": all(
            bool(item["route_metrics"]["visible_source_display_feature_set_equal"])
            for item in results
        ),
        "major_registered_planforms_unchanged": all(
            bool(item["route_metrics"]["major_registered_planforms_unchanged"])
            for item in results
        ),
        "source_analytical_products_unchanged": True,
        "diagnostic_review_maps_unchanged": True,
    }
    if is_full_batch:
        validation_checks["full_batch_contains_all_19_sites"] = len(results) == 19
    validation = {
        "schema": "diadem.stage6c5r-natural-capital-maps-validation.v1",
        "created_utc": utc_now(),
        "status": "PASS" if all(validation_checks.values()) else "FAIL",
        "rendered_site_count": len(results),
        "checks": validation_checks,
    }
    if validation["status"] != "PASS":
        raise RuntimeError("Natural capital-map validation failed")
    validation_name = "PRESENTATION_MAP_VALIDATION.json" if is_full_batch else "PRESENTATION_MAP_VALIDATION_PARTIAL.json"
    atomic_json(output_dir / validation_name, validation)
    readme = """# Stage 6C.5R natural capital-location maps

**Status:** WORKING PROPOSAL — REVIEW ONLY — NOT CANON.

These are lossless presentation maps derived read-only from the validated V7
Stage 6C.5R physical-context output.  The existing nine-panel review maps remain
the technical diagnostics and were not changed.

The terrain background is a continuous, shape-preserving display interpolation
of the active 100 m elevation authority plus the already-validated physical
conditioning residual.  Relief shading and contours receive a 50 m display-only
low-pass filter so source-cell seams do not masquerade as landforms.  It adds no
random noise or fictional microrelief.

Accepted major waterways use their original registered source planforms.
Grid-derived minor waterways receive a display-only, topology-locked fit inside
the local lens plus an 80 m halo.  Exact endpoints and confluences are retained,
continuous bidirectional displacement is held below 50 m, and a non-periodic
centreline prior is weakly informed by the unconditioned terrain only where the
parent surface distinguishes a local low.  New crossings are forbidden.  This
never changes the analytical route.  Generated runoff potential is not drawn as
an existing river.  Waterway line weight communicates hierarchy, not observed
bank-to-bank width.

Where a 100 m water category reaches a map edge as a monotone staircase, the
presentation uses an area-preserving continuous shoreline rather than enlarging
the source cells.  A clearly grid-derived polygon shoreline may likewise be
generalised within approximately half the source-cell diagonal, with topology
and area protected.  The source mask and geometry remain the analytical
authority.  Channel axes inside open water are shown as subdued thalwegs instead
of land-river ribbons.  Seasonal water is deliberately feathered as a possible
extent rather than given a falsely precise fixed shoreline.

The hollow diamond is the retained review coordinate, not a final settlement
footprint.  For specialist cavern, underwater or lagoon sites, the map presents
surface/interface context only; later 3D work remains separate.
"""
    if is_full_batch:
        (output_dir / "README.md").write_text(readme, encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pilot", action="store_true", help="Render four deliberately different sites")
    parser.add_argument("--site", action="append", default=[], help="Render one settlement ID; repeatable")
    parser.add_argument("--self-test", action="store_true", help="Run renderer unit checks without opening project data")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        print("SELF_TEST_PASS")
        return 0
    selection = tuple(args.site) if args.site else PILOT_IDS if args.pilot else None
    manifest = run(args.output_dir, selection)
    print(canonical_json({"status": "PASS", "site_count": manifest["site_count"], "output_dir": str(args.output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
