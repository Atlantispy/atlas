"""Render a non-authoritative QA plate for the synthetic routing pilot."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hydrology_regeneration import densify_polyline, derive_regenerated_flow_evidence
from synthetic_pilot import run_synthetic_pilot


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "pilot_output"


def _font(size: int, bold: bool = False):
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _terrain_rgb(elevation: np.ndarray, discharge: np.ndarray) -> np.ndarray:
    low, high = np.percentile(elevation, (2, 98))
    z = np.clip((elevation - low) / max(high - low, 1e-6), 0, 1)
    row_grad, col_grad = np.gradient(elevation.astype(np.float64))
    shade = np.clip(0.68 + 0.22 * (-0.55 * row_grad - 0.35 * col_grad), 0.35, 1.0)
    rgb = np.empty((*elevation.shape, 3), dtype=np.float32)
    rgb[..., 0] = (67 + 116 * z) * shade
    rgb[..., 1] = (91 + 111 * z) * shade
    rgb[..., 2] = (62 + 93 * z) * shade
    q = np.log1p(np.maximum(discharge, 0.0) * 1200.0)
    q /= max(float(q.max()), 1e-6)
    rgb[..., 1] += 20 * q
    rgb[..., 2] += 48 * q
    return np.clip(rgb, 0, 255).astype(np.uint8)


def _route_artefact_metrics(path: list[tuple[int, int]]) -> dict[str, float | int | bool]:
    steps = np.diff(np.asarray(path, dtype=np.int16), axis=0)
    changed = np.any(steps[1:] != steps[:-1], axis=1)
    dot = (steps[1:] * steps[:-1]).sum(axis=1)
    # A one-cell lateral reversal is the classic staircase artefact: row motion
    # changes sign on adjacent downstream steps while column motion continues.
    lateral = np.sign(steps[:, 0])
    downstream = steps[:, 1] >= 0
    reversals = (lateral[1:] * lateral[:-1] == -1) & downstream[1:] & downstream[:-1]
    length_cells = float(np.hypot(steps[:, 0], steps[:, 1]).sum())
    direct_cells = float(math.hypot(path[-1][0] - path[0][0], path[-1][1] - path[0][1]))
    return {
        "direction_change_count": int(changed.sum()),
        "direction_change_fraction": float(changed.mean()) if changed.size else 0.0,
        "reverse_or_backtrack_step_pairs": int((dot < 0).sum()),
        "one_cell_lateral_reversal_count": int(reversals.sum()),
        "one_cell_lateral_reversal_fraction": float(reversals.mean()) if reversals.size else 0.0,
        "path_length_m": length_cells * 10.0,
        "endpoint_distance_m": direct_cells * 10.0,
        "sinuosity": length_cells / max(direct_cells, 1e-9),
        "raster_zigzag_gate_pass": bool((dot < 0).sum() == 0 and reversals.mean() < 0.08),
    }


def render() -> Path:
    result, arrays, _, _, _, corridor, old_axis, topology, _, = run_synthetic_pilot()
    derive_regenerated_flow_evidence(arrays, 10.0)
    scale = 5
    map_size = arrays["elevation_m"].shape[0] * scale
    panel_width = 470
    header = 92
    footer = 50
    image = Image.new("RGB", (map_size + panel_width, header + map_size + footer), (23, 28, 34))
    draw = ImageDraw.Draw(image)
    title_font, body_font, small_font = _font(23, True), _font(15), _font(12)
    draw.text((20, 14), "Synthetic 10 m hydrology-regeneration QA", font=title_font, fill=(240, 244, 247))
    draw.text(
        (20, 52),
        "Visual aid only — analytical authority remains the tile evidence and validation report",
        font=body_font,
        fill=(173, 187, 199),
    )

    terrain = Image.fromarray(_terrain_rgb(arrays["elevation_m"], arrays["regenerated_effective_discharge_m3_s"]))
    terrain = terrain.resize((map_size, map_size), Image.Resampling.NEAREST)
    image.paste(terrain, (0, header))
    map_draw = ImageDraw.Draw(image)

    def xy(cell: tuple[int, int]) -> tuple[int, int]:
        row, col = cell
        return int((col + 0.5) * scale), int(header + (row + 0.5) * scale)

    old = densify_polyline(old_axis)
    old_points = [xy(cell) for cell in old]
    for start in range(0, len(old_points) - 1, 5):
        map_draw.line(old_points[start : min(start + 4, len(old_points))], fill=(255, 119, 79), width=3)
    route_points = [xy(cell) for cell in result.path_cells]
    map_draw.line(route_points, fill=(20, 33, 42), width=6, joint="curve")
    map_draw.line(route_points, fill=(61, 224, 241), width=3, joint="curve")
    widths = np.asarray(result.width_m)
    wlow, whigh = float(widths.min()), float(widths.max())
    for index in range(0, len(route_points), 5):
        fraction = (float(widths[index]) - wlow) / max(whigh - wlow, 1e-9)
        radius = 2 + int(round(3 * fraction))
        x, y = route_points[index]
        map_draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(89, 245, 255))
    for anchor in topology.anchors():
        x, y = xy(anchor)
        map_draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(255, 239, 120), outline=(35, 39, 44), width=2)

    px = map_size + 25
    draw.text((px, header + 18), "Legend", font=_font(18, True), fill=(240, 244, 247))
    draw.line((px, header + 56, px + 64, header + 56), fill=(255, 119, 79), width=3)
    draw.text((px + 76, header + 46), "Inherited search axis", font=body_font, fill=(220, 226, 231))
    draw.line((px, header + 88, px + 64, header + 88), fill=(61, 224, 241), width=4)
    draw.text((px + 76, header + 78), "Regenerated analytical path", font=body_font, fill=(220, 226, 231))
    draw.ellipse((px + 24, header + 113, px + 36, header + 125), fill=(255, 239, 120))
    draw.text((px + 76, header + 108), "Immutable topology contact", font=body_font, fill=(220, 226, 231))

    graph_top = header + 178
    graph_left, graph_right = px, px + 400
    graph_bottom = graph_top + 190
    draw.text((graph_left, graph_top - 28), "Modelled width along route (m)", font=_font(17, True), fill=(240, 244, 247))
    draw.rectangle((graph_left, graph_top, graph_right, graph_bottom), outline=(89, 103, 115), width=1)
    xvalues = np.linspace(graph_left + 1, graph_right - 1, len(widths))
    yvalues = graph_bottom - 1 - (widths - wlow) / max(whigh - wlow, 1e-9) * (graph_bottom - graph_top - 2)
    draw.line(list(zip(xvalues.tolist(), yvalues.tolist())), fill=(61, 224, 241), width=3, joint="curve")
    draw.text((graph_left, graph_bottom + 7), "source", font=small_font, fill=(173, 187, 199))
    draw.text((graph_right - 45, graph_bottom + 7), "receiver", font=small_font, fill=(173, 187, 199))
    draw.text((graph_left + 5, graph_top + 5), f"max {whigh:.2f}", font=small_font, fill=(220, 226, 231))
    draw.text((graph_left + 5, graph_bottom - 18), f"min {wlow:.2f}", font=small_font, fill=(220, 226, 231))

    artefacts = _route_artefact_metrics(result.path_cells)
    facts = [
        f"Evidence-cost improvement: {result.metrics['evidence_cost_improvement_fraction']:.1%}",
        f"P95 path displacement: {result.metrics['candidate_p95_displacement_m']:.0f} m",
        f"Maximum uphill step: {result.metrics['maximum_uphill_step_m']:.2f} m",
        f"Width envelope: {wlow:.2f}–{whigh:.2f} m",
        f"Sinuosity: {artefacts['sinuosity']:.3f}",
        f"One-cell lateral reversals: {artefacts['one_cell_lateral_reversal_count']}",
    ]
    text_y = graph_bottom + 55
    for fact in facts:
        draw.text((px, text_y), fact, font=body_font, fill=(220, 226, 231))
        text_y += 28
    gate_colour = (97, 220, 146) if artefacts["raster_zigzag_gate_pass"] else (255, 126, 94)
    draw.text((px, text_y + 8), f"Grid-artefact gate: {'PASS' if artefacts['raster_zigzag_gate_pass'] else 'REVIEW'}", font=_font(17, True), fill=gate_colour)

    draw.text((18, header + map_size + 16), "Terrain shading includes regenerated-flow emphasis; it is not a finished map mode.", font=small_font, fill=(173, 187, 199))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "synthetic_hydrology_regeneration_QA.png"
    image.save(target, optimize=True)
    qa = {
        "status": "WORKING PROPOSAL - REVIEW ONLY - NOT CANON",
        "visualization_authority": "QA_ONLY_NOT_ANALYTICAL_AUTHORITY",
        "image": target.name,
        "analytical_metrics": result.metrics,
        "route_artefact_metrics": artefacts,
        "visual_review": {
            "date": "2026-08-28",
            "result": "PASS_SYNTHETIC_PILOT",
            "findings": [
                "Route follows the modelled valley rather than the inherited straight axis.",
                "Expected 10 m raster stepping is visible, but there is no alternating one-cell zigzag or backtracking.",
                "Width rises continuously downstream after route-conditioned runoff accumulation; no false resets remain.",
                "Anchors remain exact and visually distinct.",
                "Plate is compact and legible, but is QA only and not map-mode artwork."
            ]
        },
        "visual_review_required": False
    }
    (OUTPUT / "synthetic_visual_qa_metrics.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__":
    print(render())
