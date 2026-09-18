#!/usr/bin/env python3
"""Render bounded actual-code diagnostics, never invented tectonic landscapes.

Source and reference files are read-only. The new output directory receives PNGs
and a provenance manifest; it is not an authoritative restart store. Matplotlib
is optional and imported only for rendering. No networking, source acquisition,
reference requalification, general simulation or automatic approval occurs here.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT/'src'))

from atlas_tectonics.timebase import JULIAN_MEGAYEAR

# Segment symbols express polarity/non-subduction, NOT step-level fault class.
# The supplied PB2002 original README is the authority for these exact meanings.
SEGMENT_LABELS = {
    '-': 'Non-subducting (not necessarily transform)',
    '/': 'Subduction: right-hand plate beneath left',
    '\\': 'Subduction: left-hand plate beneath right',
}
CAMERAS = ((0., 0.), (90., 0.), (180., 0.), (270., 0.), (0., 90.), (0., -90.))


def formation_age_lookup(state):
    """One age per sampled unit ONLY when all contributing cohorts agree.

    A mixture of formation histories does not become their average. Missing or
    unequal dates stay unknown in this scalar display, with all component records
    retained in its manifest. The physical sampler and stored records are intact.
    """
    cohorts = {d.cohort.cohort_id: d for d in state.case.cohorts}
    ages = np.full(len(state.units), np.nan)
    known = np.zeros(len(state.units), dtype=bool)
    records = []
    for i, unit in enumerate(state.units):
        components = []
        for component in unit.layer.components:
            desc = cohorts[component.cohort_id]
            time = desc.cohort.formation_time_s
            age = None if time is None else (state.case.time_s-time)/JULIAN_MEGAYEAR.seconds_per_unit
            if age is not None and (not math.isfinite(age) or age < 0):
                raise ValueError('formation age must be finite and non-negative')
            components.append({'cohort_id': component.cohort_id,
                'material_id': desc.cohort.material_id, 'source_id': desc.source_id,
                'formation_time_s': time, 'age_ma': age,
                'declared_matrix_fraction': component.solid_volume_fraction})
        contributing = [c for c in components if c['declared_matrix_fraction'] > 0]
        values = [c['age_ma'] for c in contributing]
        if values and all(v is not None for v in values) and len(set(values)) == 1:
            ages[i] = values[0]; known[i] = True
        records.append({'unit_code': i, 'unit_id': unit.unit_id,
            'layer_id': unit.layer.layer_id, 'components': components,
            'single_formation_age_known': bool(known[i])})
    return ages, known, records


def ages_for_codes(codes, lookup, known):
    """Validate sample-to-record joins; negative codes may not index from the end."""
    codes = np.asarray(codes)
    if codes.dtype.kind not in 'iu' or np.any(codes < 0) or np.any(codes >= len(lookup)):
        raise ValueError('sample unit codes do not reference the supplied state')
    return np.asarray(lookup)[codes], np.asarray(known, dtype=bool)[codes]


def boundary_label(curve):
    if curve.kind != 'boundary' or len(curve.name) != 5 or curve.name[2] not in SEGMENT_LABELS:
        raise ValueError('not a supported PB2002 boundary segment title')
    return SEGMENT_LABELS[curve.name[2]]


def lonlat_vectors(coords):
    q = np.deg2rad(np.asarray(coords, dtype=float))
    if q.ndim != 2 or q.shape[1] != 2 or not np.isfinite(q).all() or np.any(abs(q[:, 1]) > np.pi/2):
        raise ValueError('finite longitude/latitude pairs required')
    return np.column_stack((np.cos(q[:, 1])*np.cos(q[:, 0]),
                            np.cos(q[:, 1])*np.sin(q[:, 0]), np.sin(q[:, 1])))


def densify_arc(a, b, *, max_angle_deg=0.35):
    """Sample the existing minor great-circle arc for display, not new geometry."""
    if not math.isfinite(max_angle_deg) or not 0 < max_angle_deg <= 5:
        raise ValueError('bounded positive display angle required')
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != (3,) or b.shape != (3,) or not np.isfinite([a, b]).all():
        raise ValueError('finite direction triples required')
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        raise ValueError('zero direction')
    a, b = a/np.linalg.norm(a), b/np.linalg.norm(b)
    angle = math.atan2(float(np.linalg.norm(np.cross(a, b))), float(a@b))
    if angle < 1e-14:
        return np.stack((a, b))  # Exact source repetition remains a repetition.
    if np.pi-angle < 1e-12:
        raise ValueError('ambiguous antipodal display arc')
    t = np.linspace(0., 1., max(2, math.ceil(angle/math.radians(max_angle_deg))+1))
    q = (np.sin((1-t)*angle)[:, None]*a + np.sin(t*angle)[:, None]*b)/math.sin(angle)
    return q/np.linalg.norm(q, axis=1)[:, None]


def densify_curve(coords):
    q = lonlat_vectors(coords)
    pieces = [densify_arc(a, b)[:-1] for a, b in zip(q[:-1], q[1:])]
    return np.vstack((*pieces, q[-1:]))


def seam_segments(vectors):
    """Split at +/-180 with the actual great-circle/seam intersection inserted.

    Longitudes are normalised only in the display view; original PB2002 coordinates
    (including 180..360 values) and source identities are never rewritten.
    """
    q = np.asarray(vectors, dtype=float)
    ll = np.rad2deg(np.column_stack((np.arctan2(q[:, 1], q[:, 0]),
                                    np.arctan2(q[:, 2], np.hypot(q[:, 0], q[:, 1])))))
    parts, current = [], [ll[0]]
    for i in range(1, len(q)):
        prev, cur = ll[i-1], ll[i]
        if abs(cur[0]-prev[0]) > 180:
            a, b = q[i-1], q[i]
            denominator = a[1]-b[1]
            if denominator == 0:
                raise ValueError('unresolved antimeridian display crossing')
            t = a[1]/denominator
            crossing = a+t*(b-a); crossing /= np.linalg.norm(crossing)
            latitude = math.degrees(math.atan2(crossing[2], math.hypot(crossing[0], crossing[1])))
            edge = 180. if prev[0] >= 0 else -180.
            current.append(np.array([edge, latitude])); parts.append(np.asarray(current))
            current = [np.array([-edge, latitude]), cur]
        else:
            current.append(cur)
    if len(current) > 1:
        parts.append(np.asarray(current))
    return parts


def camera_axes(lon_deg, lat_deg):
    lon, lat = np.deg2rad([lon_deg, lat_deg])
    return (np.array([np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)]),
            np.array([-np.sin(lon), np.cos(lon), 0.]),
            np.array([-np.sin(lat)*np.cos(lon), -np.sin(lat)*np.sin(lon), np.cos(lat)]))


def visible_segments(vectors, lon_deg, lat_deg):
    """Orthographic projection with analytic clipping at the visible limb."""
    front, right, up = camera_axes(lon_deg, lat_deg)
    out, current = [], []
    q = np.asarray(vectors)
    for a, b in zip(q[:-1], q[1:]):
        da, db = float(a@front), float(b@front)
        if da < 0 and db < 0:
            if len(current) > 1: out.append(np.asarray(current))
            current = []; continue
        aa, bb = a, b
        if (da < 0) != (db < 0):
            crossing = a + da/(da-db)*(b-a)
            crossing /= np.linalg.norm(crossing)
            if da < 0: aa = crossing
            else: bb = crossing
        pa, pb = np.array([aa@right, aa@up]), np.array([bb@right, bb@up])
        if not current: current.append(pa)
        current.append(pb)
        if db < 0:
            out.append(np.asarray(current)); current = []
    if len(current) > 1: out.append(np.asarray(current))
    return out


def _array_hash(a):
    a = np.ascontiguousarray(a)
    return {'dtype': a.dtype.str, 'shape': list(a.shape), 'sha256': hashlib.sha256(a.tobytes()).hexdigest()}


def render(output):
    """Finite visual regression using existing supported cases and no new physics."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from atlas_tectonics import (PreparedPrecursor, SphericalFrame, PlateLayoutSettings, generate_plate_layout)
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.plate_reference_dataset import load_pb2002
    sys.path.insert(0, str(ROOT/'tools')); sys.path.insert(0, str(ROOT))
    from prepare_precursor_example import build_example
    from verify import source_inventory
    before = source_inventory(ROOT)
    budget = WorkBudget(256 << 20)
    state = build_example(budget=budget)
    case = state.case
    # Fixed finite display grid; extents come from the real example support.
    left, bottom, right, top = case.topology.domain.bounds
    maximum_depth = min(c.lithosphere_thickness_m for c in case.columns)
    xe = np.linspace(left, right, 321); ze = np.linspace(0., maximum_depth, 161)
    xx, zz = np.meshgrid((xe[:-1]+xe[1:])/2, (ze[:-1]+ze[1:])/2)
    points = np.column_stack((xx.ravel(), np.full(xx.size, (bottom+top)/2)))
    request = dict(frame_id=case.topology.frame_id, epoch_id=case.epoch_id, depth_reference_id=case.depth_reference_id)
    with PreparedPrecursor(state, budget=budget) as plan:
        samples = plan.sample_points(points, zz.ravel(), **request)
    lookup, known, records = formation_age_lookup(state)
    ages, age_known = ages_for_codes(samples.array('unit_code'), lookup, known)
    if not age_known.all():
        raise ValueError('the registered visual example no longer has single known formation ages')
    def save(fig, name):
        fig.savefig(output/name, dpi=170, bbox_inches='tight'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 6))
    im = ax.pcolormesh(xe/1000, ze/1000, ages.reshape(xx.shape), shading='flat')
    fig.colorbar(im, ax=ax, label='Formation age (million Julian years)', ticks=np.unique(ages))
    ax.invert_yaxis(); ax.set(xlabel='Horizontal distance (km)', ylabel='Depth below authored surface (km)',
        title='Atlas R2 | formation ages from actual sampled cohorts\nAuthored static example, not a simulated crust-age history')
    for age in np.unique(ages):
        mask = (ages == age).reshape(xx.shape)
        ax.text(float(xx[mask].mean()/1000), float(zz[mask].mean()/1000), f'{age:g} Ma', ha='center', va='center',
                bbox=dict(boxstyle='round,pad=0.25', alpha=.8))
    fig.tight_layout(); save(fig, 'formation_age_corrected.png')

    dataset = load_pb2002(ROOT/'reference_data/pb2002', budget=budget)
    grouped = {key: [] for key in SEGMENT_LABELS}; counts = Counter()
    for curve in dataset.boundaries:
        boundary_label(curve)
        symbol = curve.name[2]; counts[symbol] += 1
        grouped[symbol].extend(seam_segments(densify_curve(curve.coordinates)))
    fig, ax = plt.subplots(figsize=(12, 6.4))
    for symbol, style in zip(SEGMENT_LABELS, ('solid', 'dashed', 'dotted')):
        ax.add_collection(LineCollection(grouped[symbol], linewidths=.8, linestyles=style,
            label=f'{SEGMENT_LABELS[symbol]}: {counts[symbol]} segments'))
    ax.set(xlim=(-180, 180), ylim=(-90, 90), xlabel='Longitude (degrees)', ylabel='Latitude (degrees)',
        title='PB2002 | source segment polarity and non-subduction\nReference data, not Atlas-generated plate boundaries or step-level fault classes')
    ax.grid(alpha=.2); ax.legend(loc='upper center', bbox_to_anchor=(.5, -.14), fontsize=9)
    fig.text(.5, .01, 'Peter Bird (2003), doi:10.1029/2001GC000252 | fraxen/tectonicplates 339b0c5 | ODC-By 1.0',
             ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .06, 1, 1)); save(fig, 'pb2002_segment_inventory_corrected.png')

    settings = PlateLayoutSettings(12, 41, 512)
    world = generate_plate_layout(SphericalFrame(6_371_000., 'comparison-not-Earth-reconstruction'), settings, budget=budget)
    arcs = [densify_arc(*world.vertex_directions[world.edge_vertices[e]]) for e in world.interplate_edges]
    grid = []
    for lon in range(-180, 180, 30):
        grid.append(lonlat_vectors(np.column_stack((np.full(721, lon), np.linspace(-90, 90, 721)))))
    for lat in range(-60, 61, 30):
        grid.append(lonlat_vectors(np.column_stack((np.linspace(-180, 180, 1441), np.full(1441, lat)))))
    for lon, lat in CAMERAS:
        fig, ax = plt.subplots(figsize=(7.5, 8))
        ax.add_patch(plt.Circle((0, 0), 1, fill=False, linewidth=.9))
        ax.add_collection(LineCollection([p for q in grid for p in visible_segments(q, lon, lat)], linewidths=.45, alpha=.3, linestyles='dashed'))
        ax.add_collection(LineCollection([p for q in arcs for p in visible_segments(q, lon, lat)], linewidths=.9))
        ax.set(aspect='equal', xlim=(-1.04, 1.04), ylim=(-1.04, 1.04)); ax.axis('off')
        name = 'north_pole' if lat == 90 else 'south_pole' if lat == -90 else f'lon_{int(lon):03d}'
        view = 'North pole' if lat == 90 else 'South pole' if lat == -90 else f'Longitude {lon:g}°, latitude {lat:g}°'
        ax.set_title(f'Atlas | actual connected plate candidate\n{view}', fontsize=13)
        fig.text(.5, .025, '12 plates | seed 41 | 512 support cells\nStatistical geometry candidate; no physical plate-formation acceptance', ha='center', fontsize=9)
        fig.tight_layout(rect=(0, .065, 1, 1)); save(fig, 'globe_'+name+'.png')
    all_vertices = world.vertex_directions
    seen = np.max(np.column_stack([all_vertices@camera_axes(*v)[0] for v in CAMERAS]), axis=1) >= 0
    after = source_inventory(ROOT)
    if before != after or not seen.all():
        raise ValueError('source changed or six-view directional coverage is incomplete')
    source_origins = {o.source_id: o.kind for o in state.origins}
    record = {
        'schema': 'atlas.visual-qa.v1', 'status': 'RENDERED_AWAITING_VISUAL_REVIEW',
        'scope': 'actual static example sampling, raw reference display and fixed geometric candidate only',
        'source_sha256_before': before, 'source_sha256_after': after, 'source_unchanged': before == after,
        'state_id': state.state_id, 'sample_id': samples.sample_id, 'formation_units': records,
        'source_origin_kinds': source_origins,
        'cooling_history': [{'profile_id': h.profile_id, 'source_id': h.source_id,
            'cooling_age_ma': None if h.start_time_s is None else (case.time_s-h.start_time_s)/JULIAN_MEGAYEAR.seconds_per_unit}
            for h in state.cooling_history],
        'sample_grid': [160, 320], 'formation_age_ma': _array_hash(ages),
        'sampled_unit_codes': _array_hash(samples.array('unit_code')),
        'pb2002': {'dataset_id': dataset.dataset_id, 'source_hashes': dict(dataset.raw_sha256),
            'segment_symbol_counts': dict(counts), 'symbol_labels': SEGMENT_LABELS,
            'raw_curves_not_morphology_acceptance': True,
            'attribution': 'Peter Bird (2003), doi:10.1029/2001GC000252; fraxen/tectonicplates 339b0c56563c118307b1f4542703047f5f698fae; ODC-By 1.0'},
        'candidate': {'atlas_id': world.atlas_id, 'seed': 41, 'plate_count': 12, 'support_cells': 512,
            'interplate_edges': len(arcs), 'camera_lon_lat_deg': CAMERAS,
            'all_vertex_directions_visible_in_view_set': bool(seen.all()),
            'antimeridian_crossing_arcs': sum(len(seam_segments(q)) > 1 for q in arcs),
            'display_max_arc_angle_deg': .35},
        'budget': budget.statistics(),
        'claims': {'physical_validation': False, 'thermal_evolution': False, 'global_simulation': False,
                   'human_visual_review_completed': False},
        'outputs': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.glob('*.png'))},
    }
    (output/'visual_manifest.json').write_text(json.dumps(record, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new diagnostic directory; existing destinations refused')
    args = parser.parse_args(argv)
    destination = args.output.absolute()
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError('linked output destinations are refused')
    if destination.exists():
        raise FileExistsError('visual output already exists; use a new directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    claim = destination.with_name(destination.name+'.preparing')
    fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    stage = None
    try:
        stage = Path(tempfile.mkdtemp(prefix='.atlas-visual-', dir=destination.parent))
        record = render(stage)
        if destination.exists():
            raise FileExistsError('output destination appeared during rendering')
        stage.rename(destination)
        print(json.dumps({'status': record['status'], 'output_files': list(record['outputs']),
                          'source_unchanged': record['source_unchanged']}))
    finally:
        if stage is not None and stage.exists(): shutil.rmtree(stage)
        claim.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ImportError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'BLOCKED_VISUAL_QA', 'error': str(exc)}), file=sys.stderr)
        raise SystemExit(2)
