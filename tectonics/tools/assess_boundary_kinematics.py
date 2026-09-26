"""Matched-scale plate-boundary shape and relative-motion diagnostics.

SPDX-License-Identifier: AGPL-3.0-only
One declared protocol measures every source identically: saved generated worlds,
a neutral boundary/rotation JSON file (for prototypes) and PB2002. Each boundary
line between junctions is sampled at equal path-length intervals at named physical
spacings. Relative rigid-plate motion is evaluated at every chord midpoint; the
report gives bend angles, obliquity, opening/shortening/shear-dominated length and
sign changes of the normal component, plus the same values at native resolution.

Descriptive diagnostics only: no realism score, acceptance threshold or generator gate.
PB2002 follows the registered reference protocol: the development split by
default; the withheld split only with an explicit run name, recorded as
validation use. Inputs are opened read-only and never repaired or rewritten.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_FILE = Path(__file__).resolve()
_LOADED_HASH = hashlib.sha256(_FILE.read_bytes()).hexdigest()

SCHEMA = 'atlas.boundary-kinematics-assessment.v1'
INPUT_SCHEMA = 'atlas.boundary-kinematics-input.v1'
PROTOCOL_SCHEMA = 'atlas.boundary-kinematics-protocol.v1'
YEAR_S = 365.25*86400.                 # Julian year, as new_world_motion.YEAR.
CM_PER_YEAR = 100.*YEAR_S              # m/s to cm/year.
# The registered PB2002 observation scales (plate_reference_acceptance); a test
# keeps them identical rather than importing a value that could drift silently.
DEFAULT_SPACINGS_M = (100_000., 250_000., 500_000.)
DEFAULT_SHEAR_OBLIQUITY_DEG = 70.
QUANTILES = (0., .1, .25, .5, .75, .9, 1.)
BEND_BINS_DEG = (0., 5., 10., 20., 30., 45., 60., 90., 180.)
OBLIQUITY_BINS_DEG = (0., 10., 20., 30., 40., 50., 60., 70., 80., 90.)
MAX_LINES, MAX_POINTS, MAX_INPUT_BYTES = 100_000, 2_000_000, 64 << 20
# Floating-point envelope per chord, in units of eps*|omega_right-omega_left|*R.
# A conservative roundoff guard for short-chord direction and motion arithmetic;
# not a proved forward-error bound or an estimate of source/geological uncertainty.
_ENVELOPE = 8.
_EPS = float(np.finfo(float).eps)
_MIN_ARC = 1e-12    # Shorter source edges are degenerate, not boundary length.


class BoundaryAssessmentError(ValueError):
    """Refused input or protocol; never a partial or repaired measurement."""


def _fail(message):
    raise BoundaryAssessmentError(message)


def _source_hash():
    if hashlib.sha256(_FILE.read_bytes()).hexdigest() != _LOADED_HASH:
        _fail('Assessment tool changed while loaded; restart explicitly.')
    return _LOADED_HASH


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def protocol(spacings_m=DEFAULT_SPACINGS_M, shear_obliquity_deg=DEFAULT_SHEAR_OBLIQUITY_DEG):
    """The declared measurement; its identity lets reports prove they match."""
    try:
        supplied = list(spacings_m)
    except TypeError:
        _fail('Spacings must be a sequence of finite positive lengths.')
    if any(not _finite_number(s) for s in supplied):
        _fail('Spacings must be a sequence of finite positive lengths.')
    spacings = [float(s) for s in supplied]
    if (not 1 <= len(spacings) <= 16 or any(not math.isfinite(s) or s <= 0 for s in spacings)
            or spacings != sorted(set(spacings))):
        _fail('Spacings must be 1-16 distinct increasing positive lengths in metres.')
    if not _finite_number(shear_obliquity_deg):
        _fail('The shear-dominated obliquity must be a finite number.')
    threshold = float(shear_obliquity_deg)
    if not math.isfinite(threshold) or not 0 < threshold < 90:
        _fail('The shear-dominated obliquity must lie strictly between 0 and 90 degrees.')
    record = dict(
        schema=PROTOCOL_SCHEMA, spacings_m=spacings, shear_obliquity_deg=threshold,
        quantile_probabilities=list(QUANTILES), bend_bins_deg=list(BEND_BINS_DEG),
        obliquity_bins_deg=list(OBLIQUITY_BINS_DEG),
        lines=('Boundary pieces join into one line only where exactly two piece ends of the same '
               'plate pair meet at bit-identical points; lines otherwise end at junctions or at '
               'source record ends. Both sides must agree along a line.'),
        junctions=('Junctions are recognised only where pieces end; a boundary passing through a '
                   'junction without ending there is not split.'),
        division=('Each open line is divided at equal spacing along its path into floor(L/s + 0.5) chords, '
                  'keeping its ends; a closed line starts at its first piece (one sampling phase). '
                  'Chord lengths need not be equal and may be shorter than the represented path intervals. '
                  'Lines shorter than s/2, closed lines with fewer than 3 chords and lines whose '
                  'chords would be degenerate or antipodal are unresolved at that spacing.'),
        motion=('Relative rigid rotation evaluated at each chord midpoint. Normal component is '
                '(v_right - v_left).right_normal, positive for opening, as in step_motion and '
                'new_world_motion.'),
        signed_samples=('Every resolved line retains ordered, unrounded normal_cm_year and along_cm_year '
                        'arrays. Normal is positive for opening; along is (v_right - v_left) projected '
                        'along line travel, with the named left plate on the left as seen from outside. '
                        'line_index is zero-based in the source line list. represented_path_edges_km '
                        'contains the ordered interval edges starting at zero along that oriented source '
                        'line; sample i represents edges i to i+1. A closed line includes its closing '
                        'interval. Numerical guards and classifications do not zero these components.'),
        obliquity='0 degrees is motion normal to the chord; 90 degrees is motion along it; sign discarded.',
        numerical_envelope=('A chord is stationary when its relative speed is within '
                            '8*eps*|omega_right-omega_left|*R, and its normal component has no sign '
                            'when within 8*eps*|omega_right-omega_left|*R*(1+1/theta_chord): the '
                            'declared roundoff guard, not a proved error bound or physical threshold.'),
        classes=('stationary within the numerical envelope; shear-dominated when obliquity is at '
                 'least the declared angle; otherwise opening or shortening by the normal sign.'),
        sign_changes=('normal_component: sign changes between successive signed chords, skipping '
                      'chords whose normal component is within the numerical envelope. '
                      'dominated_class: changes between opening and shortening classes, skipping '
                      'shear-dominated and stationary chords. Closed lines include the closing pair.'),
        bends=('Turning angle between consecutive chords at each interior chord vertex, and at the '
               'closing vertex of a closed line; 0 degrees is straight.'),
        weights=('Class shares weight each chord by the boundary length it represents. Bend and '
                 'obliquity distributions count vertices and chords equally.'))
    record['protocol_id'] = hashlib.sha256(_canonical(record)).hexdigest()
    return record


# --- Spherical geometry -----------------------------------------------------

def _normalise(v):
    v = np.asarray(v, dtype=float)
    return v/np.linalg.norm(v, axis=-1, keepdims=True)


def _arc(a, b):
    """Great-circle angle, well conditioned for short and long arcs."""
    return np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a*b, axis=-1))


def _resample(points, count, closed):
    """count equal path-length intervals; open line endpoints are retained exactly."""
    arcs = _arc(points[:-1], points[1:])
    edges = np.concatenate(([0.], np.cumsum(arcs)))
    length = edges[-1]
    targets = np.arange(count + (0 if closed else 1))*(length/count)
    index = np.clip(np.searchsorted(edges, targets, side='right')-1, 0, len(arcs)-1)
    fraction = np.clip((targets-edges[index])/arcs[index], 0., 1.)[:, None]
    theta = arcs[index][:, None]
    out = _normalise((np.sin((1-fraction)*theta)*points[index]
                      + np.sin(fraction*theta)*points[index+1])/np.sin(theta))
    out[0] = points[0]
    if not closed:
        out[-1] = points[-1]
    return out


def _chords(ring, closed):
    a = ring if closed else ring[:-1]
    b = np.roll(ring, -1, axis=0) if closed else ring[1:]
    middle = _normalise(a+b)
    left = _normalise(np.cross(a+b, b-a))   # Left of travel, seen from outside.
    return middle, left, np.cross(left, middle), _arc(a, b)


def _bends(ring, closed):
    if closed:
        previous, here, following = np.roll(ring, 1, axis=0), ring, np.roll(ring, -1, axis=0)
    else:
        previous, here, following = ring[:-2], ring[1:-1], ring[2:]
    if not len(here):
        return np.zeros(0)
    incoming = np.cross(_normalise(np.cross(previous, here)), here)
    outgoing = np.cross(_normalise(np.cross(here, following)), here)
    turn = np.arctan2(np.sum(here*np.cross(incoming, outgoing), axis=1),
                      np.sum(incoming*outgoing, axis=1))
    return np.degrees(np.abs(turn))


def chord_motion(middle, left, tangent, delta, radius_m):
    """Normal (opening positive), along-chord and total relative speed, in m/s.

    delta is omega_right - omega_left in rad/s; left is the chord's left normal.
    """
    relative = np.cross(np.asarray(delta, dtype=float), middle)*radius_m
    return (-np.sum(relative*left, axis=-1), np.sum(relative*tangent, axis=-1),
            np.linalg.norm(relative, axis=-1))


def signed_motion(normal, speed, chord_arcs, delta_norm, radius_m):
    """Moving mask and normal signs outside each chord's floating-point envelope."""
    scale = _ENVELOPE*_EPS*float(delta_norm)*radius_m
    moving = speed > scale
    signed = moving & (np.abs(normal) > scale*(1.+1./np.asarray(chord_arcs, dtype=float)))
    return moving, np.where(signed, np.sign(normal), 0.)


def _changes(signs, closed):
    kept = [s for s in signs if s]
    if len(kept) < 2:
        return 0
    pairs = zip(kept, kept[1:] + (kept[:1] if closed else []))
    return sum(a != b for a, b in pairs)


# --- Boundary lines ---------------------------------------------------------

@dataclass(frozen=True, eq=False)
class BoundaryLine:
    """One oriented line between junctions: left/right plates as seen from outside."""
    left: str
    right: str
    points: np.ndarray
    closed: bool


def _chain(pieces):
    """Join (start_key, end_key, points, left, right) pieces into BoundaryLines."""
    if not pieces:
        _fail('No boundary pieces were supplied.')
    ends = defaultdict(list)
    for i, (start, end, _, _, _) in enumerate(pieces):
        ends[start].append(i)
        ends[end].append(i)

    def pair(i):
        return frozenset(pieces[i][3:5])

    def through(key):
        items = ends[key]
        return len(items) == 2 and items[0] != items[1] and pair(items[0]) == pair(items[1])

    used = [False]*len(pieces)

    def oriented(i, key):
        start, end, points, left, right = pieces[i]
        if key == start:
            return end, points, left, right
        return start, points[::-1], right, left

    def walk(first, key):
        parts, sides, current, loop_key = [], None, first, key
        while True:
            used[current] = True
            key, points, left, right = oriented(current, key)
            if sides is None:
                sides = (left, right)
            elif sides != (left, right):
                _fail('Boundary sides disagree along one line; inconsistent source orientation.')
            parts.append(points if not parts else points[1:])
            if key == loop_key or not through(key):
                break
            current = next(j for j in ends[key] if j != current)
            if used[current]:
                break
        points = np.concatenate(parts)
        # Closed only when nothing else meets the return point: a line that leaves
        # and re-enters one junction stays an open line between junction ends.
        closed = bool(key == loop_key and sorted(ends[loop_key]) == sorted((first, current))
                      and len(points) > 3)
        return BoundaryLine(sides[0], sides[1], points, closed)

    lines = []
    for i in range(len(pieces)):
        if used[i] or (through(pieces[i][0]) and through(pieces[i][1])):
            continue
        start = pieces[i][0] if not through(pieces[i][0]) else pieces[i][1]
        lines.append(walk(i, start))
    for i in range(len(pieces)):   # Remaining pieces form closed loops.
        if not used[i]:
            lines.append(walk(i, pieces[i][0]))
    if len(lines) > MAX_LINES:
        _fail('Too many boundary lines for one bounded assessment.')
    for line in lines:
        arcs = _arc(line.points[:-1], line.points[1:])
        if np.any(arcs <= _MIN_ARC) or np.any(arcs >= math.pi-1e-9):
            _fail('Boundary line has a degenerate or antipodal edge.')
        line.points.setflags(write=False)
    return lines


# --- Measurement ------------------------------------------------------------

def _summary(values, bins):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return dict(count=0)
    counts = np.histogram(values, bins=np.asarray(bins))[0]
    return dict(count=int(len(values)), mean=float(values.mean()),
                quantiles=[float(q) for q in np.quantile(values, QUANTILES)],
                histogram=dict(edges_deg=list(bins), counts=[int(c) for c in counts]))


def _profile(lines, angular, radius_m, spacing_m, threshold_deg):
    """One source at one spacing (None: native vertices). Returns (report, raw)."""
    resolved = unresolved = 0
    resolved_length = unresolved_length = 0.
    bends, obliquities, speeds, weights = [], [], [], []
    shares = dict(opening=0., shortening=0., shear_dominated=0., stationary=0.)
    signed_samples = []
    normal_changes = class_changes = chord_count = 0
    if spacing_m is not None:
        planned = 0
        for line in lines:
            ratio = float(np.sum(_arc(line.points[:-1], line.points[1:])))*radius_m/spacing_m
            if not math.isfinite(ratio) or ratio > MAX_POINTS:
                _fail('Spacing is too fine for one bounded assessment.')
            planned += math.floor(ratio + .5)
            if planned > MAX_POINTS:
                _fail('Spacing is too fine for one bounded assessment.')
    for line_index, line in enumerate(lines):
        points, closed = line.points, line.closed
        length = float(np.sum(_arc(points[:-1], points[1:])))
        sample_record = dict(line_index=line_index, left_plate=line.left, right_plate=line.right,
                             closed=closed)
        if spacing_m is None:
            ring = points[:-1] if closed else points
        else:
            count = int(math.floor(length*radius_m/spacing_m + .5))
            ring = None if count < (3 if closed else 1) else _resample(points, count, closed)
            if ring is not None:
                arcs = _arc(ring, np.roll(ring, -1, axis=0)) if closed else _arc(ring[:-1], ring[1:])
                if np.any(arcs <= _MIN_ARC) or np.any(arcs >= math.pi-1e-9):
                    ring = None   # A chord cannot represent this line at this spacing.
            if ring is None:
                unresolved += 1
                unresolved_length += length
                signed_samples.append(dict(sample_record, status='UNRESOLVED_AT_SPACING'))
                continue
        middle, left, tangent, chord_arcs = _chords(ring, closed)
        represented = chord_arcs if spacing_m is None else np.full(len(middle), length/len(middle))
        delta = np.asarray(angular[line.right], dtype=float)-np.asarray(angular[line.left], dtype=float)
        normal, along, speed = chord_motion(middle, left, tangent, delta, radius_m)
        signed_samples.append(dict(
            sample_record, status='RESOLVED',
            represented_path_edges_km=(np.concatenate(([0.], np.cumsum(represented)))*radius_m/1000.).tolist(),
            normal_cm_year=(normal*CM_PER_YEAR).tolist(), along_cm_year=(along*CM_PER_YEAR).tolist()))
        obliquity = np.degrees(np.arctan2(np.abs(along), np.abs(normal)))
        moving, signs = signed_motion(normal, speed, chord_arcs, np.linalg.norm(delta), radius_m)
        shear = moving & (obliquity >= threshold_deg)
        opening = moving & ~shear & (normal > 0)
        shortening = moving & ~shear & (normal <= 0)
        for name, mask in (('opening', opening), ('shortening', shortening),
                           ('shear_dominated', shear), ('stationary', ~moving)):
            shares[name] += float(np.sum(represented[mask]))
        normal_changes += _changes(signs.tolist(), closed)
        class_changes += _changes(np.where(opening, 1., np.where(shortening, -1., 0.)).tolist(), closed)
        bends.append(_bends(ring, closed))
        obliquities.append(obliquity[moving])
        speeds.append(speed)
        weights.append(represented)
        chord_count += len(middle)
        resolved += 1
        resolved_length += length
    bends = np.concatenate(bends) if bends else np.zeros(0)
    obliquities = np.concatenate(obliquities) if obliquities else np.zeros(0)
    speeds = np.concatenate(speeds) if speeds else np.zeros(0)
    weights = np.concatenate(weights) if weights else np.zeros(0)
    km = radius_m/1000.
    per_1000_km = (lambda n: None) if resolved_length == 0 else (lambda n: 1000.*n/(resolved_length*km))
    total = math.fsum(shares.values())
    report = dict(
        spacing_m=spacing_m, lines=dict(resolved=resolved, unresolved=unresolved),
        length_km=dict(resolved=resolved_length*km, unresolved=unresolved_length*km),
        chords=chord_count, bend_deg=_summary(bends, BEND_BINS_DEG),
        signed_motion_samples=signed_samples,
        obliquity_deg=_summary(obliquities, OBLIQUITY_BINS_DEG),
        length_share={k: (None if total == 0 else v/total) for k, v in shares.items()},
        sign_changes=dict(normal_component=normal_changes, dominated_class=class_changes),
        sign_changes_per_1000_km=dict(normal_component=per_1000_km(normal_changes),
                                      dominated_class=per_1000_km(class_changes)),
        relative_speed_cm_year=dict(
            length_weighted_mean=None if not len(speeds) else float(np.sum(speeds*weights)/np.sum(weights))*CM_PER_YEAR,
            median=None if not len(speeds) else float(np.median(speeds))*CM_PER_YEAR))
    if spacing_m is None and len(weights):
        edges = weights*km
        report['edge_length_km'] = dict(count=int(len(edges)), mean=float(edges.mean()),
                                        quantiles=[float(q) for q in np.quantile(edges, QUANTILES)])
    return report, dict(bends=bends, obliquity=obliquities)


def measure(lines, angular, radius_m, proto):
    """Every declared spacing plus native resolution, for one source."""
    if not _finite_number(radius_m) or radius_m <= 0:
        _fail('A finite positive sphere radius is required.')
    radius_m = float(radius_m)
    if (type(proto) is not dict or 'spacings_m' not in proto or 'shear_obliquity_deg' not in proto
            or proto != protocol(proto['spacings_m'], proto['shear_obliquity_deg'])):
        _fail('The complete declared protocol and its identity must agree.')
    missing = {p for line in lines for p in (line.left, line.right)} - set(angular)
    if missing:
        _fail('Every boundary plate needs an angular velocity.')
    native, _ = _profile(lines, angular, radius_m, None, proto['shear_obliquity_deg'])
    median_edge_m = 1000.*native['edge_length_km']['quantiles'][3] if 'edge_length_km' in native else None
    scales, raw = [], []
    for spacing in proto['spacings_m']:
        report, values = _profile(lines, angular, radius_m, spacing, proto['shear_obliquity_deg'])
        # Descriptive flag: between native vertices a line is straight, so finer
        # spacings mostly measure where the source placed its vertices.
        report['finer_than_native_median_edge'] = None if median_edge_m is None else spacing < median_edge_m
        scales.append(report)
        raw.append(values)
    length = math.fsum(float(np.sum(_arc(l.points[:-1], l.points[1:]))) for l in lines)*radius_m/1000.
    return dict(radius_m=radius_m, plate_count=len(angular), boundary_lines=len(lines),
                closed_lines=sum(l.closed for l in lines), boundary_length_km=length,
                native=dict(native, note='Native vertex spacing differs between sources; not a matched comparison.'),
                scales=scales), raw


# --- Sources ------------------------------------------------------------------

def _vectors(values, what):
    if type(values) is not dict or not values:
        _fail(f'{what}: a nonempty plate-to-vector mapping is required.')
    out = {}
    for plate, vector in values.items():
        if (type(plate) is not str or not plate or type(vector) is not list or len(vector) != 3
                or any(not _finite_number(x) for x in vector)):
            _fail(f'{what}: plate IDs need finite three-vectors.')
        out[plate] = np.asarray(vector, dtype=float)
    return out


def project_source(path, proto):
    """Reopen one saved world with its retained dependency checks; never regenerate."""
    from new_world_project import load_project
    project = load_project(path)
    if project.motion is None:
        _fail('The saved project has no initial motion.')
    atlas, record = project.atlas, project.motion.descriptor()
    if record.get('atlas_id') != atlas.atlas_id or record.get('geometry_id') != atlas.geometry_id:
        _fail('Saved motion belongs to different geometry.')
    angular = _vectors(record.get('angular_velocities_rad_s'), 'Saved motion')
    if set(angular) != set(atlas.plate_ids):
        _fail('Saved rotations must cover exactly the native plates.')
    vertices, edges = atlas.vertex_directions, atlas.edge_vertices
    pieces = []
    for index in atlas.interplate_edges:
        edge = atlas.edge(int(index))
        a, b = (int(v) for v in edges[index])
        pieces.append((a, b, vertices[[a, b]], edge.left_plate_id, edge.right_plate_id))
    lines = _chain(pieces)
    measured, raw = measure(lines, angular, atlas.sphere.radius_m, proto)
    identity = dict(atlas_id=atlas.atlas_id, geometry_id=atlas.geometry_id, motion_id=project.motion.motion_id)
    return dict(kind='saved-project', label='project:'+identity['motion_id'][:12], identity=identity,
                **measured), raw, identity['motion_id'], (lines, angular, atlas.sphere.radius_m)


def _read_input(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        _fail('Use a regular local input file, not a link.')
    # Bound allocation before parsing, including a file which grows after opening.
    with path.open('rb') as stream:
        raw = stream.read(MAX_INPUT_BYTES+1)
    if not 0 < len(raw) <= MAX_INPUT_BYTES:
        _fail('Input file is empty or exceeds the bounded size.')

    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                _fail('Duplicate JSON key in input.')
            out[key] = value
        return out

    def constant(name):
        _fail('Non-finite JSON constant in input: '+name)
    try:
        return raw, json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, BoundaryAssessmentError):
            raise
        _fail('Input is not valid UTF-8 JSON.')


def input_lines(data):
    """Validate the neutral schema; pieces must share bit-identical endpoints to join."""
    if type(data) is not dict or set(data) - {'schema', 'label', 'radius_m', 'angular_velocities_rad_s',
                                              'boundaries'} or data.get('schema') != INPUT_SCHEMA:
        _fail('Unsupported neutral input schema or fields.')
    radius = data.get('radius_m')
    if not _finite_number(radius) or radius <= 0:
        _fail('radius_m must be a finite positive number.')
    angular = _vectors(data.get('angular_velocities_rad_s'), 'Input rotations')
    boundaries = data.get('boundaries')
    if type(boundaries) is not list or not 0 < len(boundaries) <= MAX_LINES:
        _fail('A bounded nonempty boundary list is required.')
    pieces, total = [], 0
    for item in boundaries:
        if type(item) is not dict or set(item) != {'left', 'right', 'points'}:
            _fail('Each boundary needs exactly left, right and points.')
        left, right, points = item['left'], item['right'], item['points']
        if (type(left) is not str or type(right) is not str
                or left not in angular or right not in angular or left == right):
            _fail('Boundary plates must differ and have rotations.')
        if (type(points) is not list or len(points) < 2 or any(
                type(p) is not list or len(p) != 3
                or any(not _finite_number(x) for x in p) for p in points)):
            _fail('Boundary points must be lists of finite Cartesian triples.')
        total += len(points)
        if total > MAX_POINTS:
            _fail('Too many boundary points for one bounded assessment.')
        # Validated as unit directions but not renormalised, so exports round-trip exactly.
        array = np.asarray(points, dtype=float)
        if np.any(np.abs(np.linalg.norm(array, axis=1)-1.) > 1e-9):
            _fail('Boundary points must be unit vectors.')
        key = lambda p: tuple(float(x)+0. for x in p)
        pieces.append((key(array[0]), key(array[-1]), array, left, right))
    return _chain(pieces), angular, float(radius)


def input_source(path, proto):
    raw, data = _read_input(path)
    lines, angular, radius = input_lines(data)
    measured, values = measure(lines, angular, radius, proto)
    digest = hashlib.sha256(raw).hexdigest()
    label = data.get('label')
    label = label if type(label) is str and 0 < len(label) <= 128 else 'input:'+digest[:12]
    return dict(kind='neutral-input', label=label, identity=dict(input_sha256=digest), **measured), values, digest


def export_input(lines, angular, radius_m, *, label=None):
    """Neutral schema for any generator; points use repr floats, so round trips are exact."""
    record = dict(schema=INPUT_SCHEMA, radius_m=float(radius_m),
                  angular_velocities_rad_s={p: [float(x) for x in w] for p, w in sorted(angular.items())},
                  boundaries=[dict(left=l.left, right=l.right, points=l.points.tolist()) for l in lines])
    if label is not None:
        record['label'] = label
    return record


def pb2002_lines(directory):
    """Policy-admitted PB2002 lines, rotations (rad/s) and each plate pair's registered split.

    The whole inventory is chained first, so junctions are identified before a
    split is selected. Splits follow record_role: a boundary touching any reserved
    plate is withheld in its entirety.
    """
    from atlas_tectonics.plate_reference_acceptance import record_role
    from atlas_tectonics.plate_reference_dataset import load_pb2002, lonlat_vectors
    from atlas_tectonics.plate_reference_use import prepare_reference_use
    plan = prepare_reference_use(directory)
    plan.require_use('source_boundary_kinematics')
    dataset = load_pb2002(directory)
    if dataset.dataset_id != plan.dataset_id:
        _fail('PB2002 inventory changed between policy and measurement.')
    per_ma = 1e6*YEAR_S
    angular = {p.plate_id: (p.vector_rad_ma/per_ma).tolist() for p in dataset.poles}
    pieces, roles, step = [], {}, 1
    key = lambda p: tuple(float(x)+0. for x in p)
    for curve in dataset.boundaries:
        left, right = curve.owners
        count = curve.count-1
        found = {record_role(observable='motion', boundary=curve.name, step_number=n)
                 for n in range(step, step+count)}
        step += count
        role = 'withheld' if 'WITHHELD_WITHIN_MODEL' in found else 'development'
        if roles.setdefault(frozenset((left, right)), role) != role:
            _fail('One PB2002 plate pair has two registered splits.')
        points = lonlat_vectors(curve.measurement_coordinates())
        pieces.append((key(points[0]), key(points[-1]), np.array(points), left, right))
    lines = _chain(pieces)
    return plan, dataset, lines, {l: roles[frozenset((l.left, l.right))] for l in lines}, angular


def pb2002_source(directory, split, run_id, proto):
    """Registered split of the audited PB2002 inventory; never tuned or repaired."""
    from atlas_tectonics.plate_reference_acceptance import evaluation_record, reference_protocol
    from atlas_tectonics.plate_reference_dataset import EARTH_REFERENCE_RADIUS_M
    if split not in ('development', 'withheld'):
        _fail('PB2002 split must be development or withheld.')
    if type(run_id) is not str or not run_id.strip():
        _fail('A named run is required for any PB2002 evaluation.')
    plan, dataset, all_lines, roles, angular = pb2002_lines(directory)
    audit = evaluation_record(dataset.dataset_id, dataset.dataset_id, split=split, run_id=run_id,
                              purpose='validation' if split == 'withheld' else 'calibration')
    lines = [line for line in all_lines if roles[line] == split]
    if not lines:
        _fail('The selected PB2002 split contains no boundary lines.')
    measured, raw = measure(lines, angular, EARTH_REFERENCE_RADIUS_M, proto)
    identity = dict(dataset_id=dataset.dataset_id, policy_id=plan.policy_id,
                    reference_protocol_id=reference_protocol()['protocol_id'], split=split)
    return dict(kind='pb2002', label='PB2002 '+split, identity=identity, audit=audit,
                evidence='One present-day model; within-model split, not independent validation.',
                **measured), raw, dataset.dataset_id


def _gap(a, b):
    a, b = np.sort(a), np.sort(b)
    grid = np.union1d(a, b)
    return float(np.max(np.abs(np.searchsorted(a, grid, side='right')/len(a)
                               - np.searchsorted(b, grid, side='right')/len(b))))


def _comparison(reference, reference_raw, candidate, candidate_raw, candidate_id, run_id):
    from atlas_tectonics.plate_reference_acceptance import evaluation_record
    split = reference['identity']['split']
    audit = evaluation_record(reference['identity']['dataset_id'], candidate_id, split=split,
                              run_id=run_id, purpose='validation' if split == 'withheld' else 'calibration')
    rows = []
    for ref, ref_raw, cand, cand_raw in zip(reference['scales'], reference_raw,
                                            candidate['scales'], candidate_raw):
        if ref['spacing_m'] != cand['spacing_m']:
            _fail('Comparison requires identical spacings.')
        row = dict(spacing_m=ref['spacing_m'])
        for name, key in (('bend_deg', 'bends'), ('obliquity_deg', 'obliquity')):
            a, b = ref_raw[key], cand_raw[key]
            row[name] = None if not len(a) or not len(b) else dict(
                reference_quantiles=ref[name]['quantiles'], candidate_quantiles=cand[name]['quantiles'],
                empirical_cdf_maximum_gap=_gap(a, b))
        row['candidate_minus_reference'] = dict(
            length_share={k: (None if cand['length_share'][k] is None or ref['length_share'][k] is None
                              else cand['length_share'][k]-ref['length_share'][k]) for k in ref['length_share']},
            sign_changes_per_1000_km={k: (None if cand['sign_changes_per_1000_km'][k] is None
                                          or ref['sign_changes_per_1000_km'][k] is None
                                          else cand['sign_changes_per_1000_km'][k]-ref['sign_changes_per_1000_km'][k])
                                      for k in ref['sign_changes_per_1000_km']})
        rows.append(row)
    return dict(candidate=candidate['label'], reference=reference['label'], audit=audit, scales=rows,
                status='DESCRIPTIVE_COMPARISON_NOT_ACCEPTANCE', scientific_threshold=None,
                note='Correlated boundaries are not independent samples; no p-value or score is implied.')


def assess(*, projects=(), inputs=(), reference='development', run_id=None,
           spacings_m=DEFAULT_SPACINGS_M, shear_obliquity_deg=DEFAULT_SHEAR_OBLIQUITY_DEG,
           pb2002_directory=None):
    """Measure every supplied source with one protocol; optionally compare to PB2002."""
    proto = protocol(spacings_m, shear_obliquity_deg)
    if reference not in ('development', 'withheld', 'none'):
        _fail('Reference must be development, withheld or none.')
    if reference == 'withheld' and run_id is None:
        _fail('The withheld PB2002 split needs an explicit named run.')
    if run_id is not None and (type(run_id) is not str or not run_id.strip() or len(run_id) > 256):
        _fail('A run name must be 1-256 characters.')
    run_id = run_id or 'boundary-kinematics-'+reference
    sources, raws, ids = [], [], []
    for path in projects:
        source, raw, identity, _ = project_source(path, proto)
        sources.append(source); raws.append(raw); ids.append(identity)
    for path in inputs:
        source, raw, identity = input_source(path, proto)
        sources.append(source); raws.append(raw); ids.append(identity)
    comparisons, reference_source = [], None
    if reference != 'none':
        directory = ROOT/'reference_data/pb2002' if pb2002_directory is None else pb2002_directory
        reference_source, reference_raw, _ = pb2002_source(directory, reference, run_id, proto)
        comparisons = [_comparison(reference_source, reference_raw, s, r, i, run_id)
                       for s, r, i in zip(sources, raws, ids)]
    if not sources and reference_source is None:
        _fail('Supply at least one project, input or PB2002 reference.')
    report = dict(schema=SCHEMA, status='WORKING NON-CANON',
        scientific_status='DESCRIPTIVE_DIAGNOSTICS_NOT_ACCEPTANCE', protocol=proto,
        tool_sha256=_source_hash(),
        runtime=dict(python_version=sys.version.split()[0], python_implementation=sys.implementation.name,
                     numpy_version=np.__version__, identity_scope='Version metadata; not a native-binary or transitive-source seal.'),
        sources=sources, reference=reference_source,
        comparisons=comparisons,
        limitations=[
            'Descriptive matched-scale diagnostics: no realism score, threshold or acceptance decision.',
            'PB2002 is one present-day model; its development/withheld split is correlated, not independent evidence.',
            'Chord ends lie on the boundary; chord midpoints may not. Motion is the relative rigid rotation there.',
            'Named spacings describe equal source-path intervals; shortcut chord lengths are generally different.',
            'Closed lines use one sampling phase, anchored to source ordering; phase sensitivity is not assessed.',
            'Bends are absolute turning angles; signed convexity/reflex geometry is not measured.',
            'Shear-dominated is a declared classification angle, not an inferred transform fault.',
            'Sign changes use the actual normal component outside a declared roundoff guard; source uncertainty is not propagated.',
            'Native-resolution values depend on each source\'s own vertex spacing and are not matched.',
            'Spacings finer than a source\'s median native edge mostly measure its vertex placement; see the flag.'])
    json.dumps(report, allow_nan=False)   # Refuse non-finite output rather than emit it.
    return report


def _write_new(path, text):
    path = Path(path)
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        _fail('The report must be a new file in an existing directory.')
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--project', action='append', default=[], metavar='WORLD.atlas',
                        help='saved world with initial motion; opened read-only (repeatable)')
    parser.add_argument('--input', action='append', default=[], metavar='BOUNDARIES.json',
                        help=f'neutral {INPUT_SCHEMA} file, e.g. from a prototype (repeatable)')
    parser.add_argument('--reference', choices=('development', 'withheld', 'none'), default='development',
                        help='PB2002 split to measure and compare against (default: development)')
    parser.add_argument('--run-id', help='evaluation name; required for the withheld split')
    parser.add_argument('--spacing-km', type=float, action='append',
                        help='override the declared spacings (repeatable; changes the protocol ID)')
    parser.add_argument('--shear-obliquity-deg', type=float, default=DEFAULT_SHEAR_OBLIQUITY_DEG)
    parser.add_argument('--report', help='new JSON file, written with LF; default is standard output')
    args = parser.parse_args(argv)
    if args.report is not None and (Path(args.report).exists() or not Path(args.report).parent.is_dir()):
        parser.error('--report must name a new file in an existing directory')
    spacings = DEFAULT_SPACINGS_M if not args.spacing_km else tuple(1000.*s for s in args.spacing_km)
    try:
        report = assess(projects=args.project, inputs=args.input, reference=args.reference,
                        run_id=args.run_id, spacings_m=spacings, shear_obliquity_deg=args.shear_obliquity_deg)
        text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n'
        if args.report is None:
            sys.stdout.buffer.write(text.encode('utf-8'))   # LF on every platform.
            sys.stdout.buffer.flush()
        else:
            _write_new(args.report, text)
    except (ValueError, OSError) as exc:   # Includes contract, reference and geometry refusals.
        print(f'REFUSED: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.path[:0] = [str(ROOT/'src')]
    raise SystemExit(main())
