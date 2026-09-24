"""Analytic crust intersections on native minor great-circle plate edges.

SPDX-License-Identifier: AGPL-3.0-only
Positive spans partition each real interplate edge. Zero-length records preserve
boundary contacts; coincident boundary spans retain every possible column owner.
Fractions measure spherical angle, never longitude or a global planar projection.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
from pathlib import Path

import numpy as np

from new_world_contract import ContractError

_FILE = Path(__file__).resolve()
_LOADED_HASH = hashlib.sha256(_FILE.read_bytes()).hexdigest()
_ROUND = 64*np.finfo(float).eps
_MIN_ARC_ANGLE = math.sqrt(np.finfo(float).eps)


@dataclass(frozen=True, slots=True)
class ArcCrustInterval:
    edge_index: int
    start_fraction: float
    end_fraction: float
    column_ids: tuple[str, ...]


def source_hash():
    digest = hashlib.sha256(_FILE.read_bytes()).hexdigest()
    if digest != _LOADED_HASH:
        raise ContractError('SOURCE_MISMATCH', 'Arc adapter changed while loaded; restart explicitly.')
    return digest


def _fail(message):
    raise ContractError('ARC_GEOMETRY_REFUSED', message)


def _arc_frame(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if (a.shape != (3,) or b.shape != (3,) or not np.isfinite(a).all()
            or not np.isfinite(b).all()
            or abs(float(np.linalg.norm(a))-1) > _ROUND
            or abs(float(np.linalg.norm(b))-1) > _ROUND):
        _fail('Finite native unit directions required.')
    cross = np.cross(a, b); sine = float(np.linalg.norm(cross))
    angle = math.atan2(sine, float(a@b))
    # Plane normal conditioning scales as 1/sin(angle). Refuse the ill-
    # conditioned end regimes instead of manufacturing a preferred great circle.
    if min(angle, math.pi-angle) <= _MIN_ARC_ANGLE:
        _fail('Degenerate or unresolved nearly-antipodal minor arc.')
    normal = cross/sine
    tangent = np.cross(normal, a)
    return angle, normal, tangent


def _parameter(point, start, tangent):
    return math.atan2(float(point@tangent), float(point@start))


def _exact_planes(a, b, c, d):
    """Rare adaptive fallback: exact predicates for the supplied binary64 bytes.

    A small determinant is not proof of coplanarity. Rational arithmetic decides
    the sign/equality without a geometry tolerance; only its resulting direction
    is converted back to binary64 for angle evaluation.
    """
    a, b, c, d = [tuple(Fraction.from_float(float(x)) for x in v) for v in (a,b,c,d)]
    def cross(x, y):
        return (x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0])
    def dot(x, y): return sum(first*last for first,last in zip(x,y))
    first, second = cross(a,b), cross(c,d)
    determinants = (dot(a,second), dot(b,second), dot(c,first), dot(d,first))
    signs = tuple((v > 0)-(v < 0) for v in determinants)
    q = cross(first,second); scale = max(map(abs,q))
    return signs, None if scale == 0 else np.asarray([float(x/scale) for x in q])


def _edge_partition(a, b, starts, ends, normals, tangents, lengths, owners):
    """Intersect supporting planes, then restrict BOTH directed minor arcs."""
    angle, normal, tangent = _arc_frame(a, b)
    events = [(0., set()), (angle, set())]
    overlaps = []

    def event(value, owner):
        if 0. <= value <= angle:
            events.append((value, {owner}))

    if len(starts):
        intersections = np.cross(normal, normals)
        magnitude = np.linalg.norm(intersections, axis=1)
        determinants = np.column_stack((normals@a, normals@b, starts@normal, ends@normal))
        for i in range(len(starts)):
            owner, c, d = owners[i], starts[i], ends[i]
            band = _ROUND*(1/math.sin(angle)+1/math.sin(float(lengths[i])))
            point = intersections[i]
            signs = tuple(int(x) for x in np.sign(determinants[i]))
            if magnitude[i] <= math.sqrt(np.finfo(float).eps) or np.any(np.abs(determinants[i]) <= band):
                signs, point = _exact_planes(a,b,c,d)
            if point is None:
                # Parameter unwraps along the query's oriented plane. Test all
                # possible 2*pi shifts; each arc is shorter than pi.
                first = _parameter(c, a, tangent)
                direction = 1. if float(normal@normals[i]) > 0 else -1.
                last = first+direction*float(lengths[i])
                low, high = sorted((first, last))
                for shift in (-2*math.pi, 0., 2*math.pi):
                    lo, hi = max(0., low+shift), min(angle, high+shift)
                    if hi < lo:
                        continue
                    event(lo, owner); event(hi, owner)
                    if hi > lo:
                        overlaps.append((lo, hi, owner))
                continue
            A,B,C,D = signs
            for sign in (1,-1):
                if sign*A >= 0 and sign*B <= 0 and sign*C <= 0 and sign*D >= 0:
                    candidate = sign*point
                    # Algebraically certified endpoint/vertex identities avoid
                    # tiny duplicate cuts without merging nearby distinct roots.
                    if A == 0: s = 0.
                    elif B == 0: s = angle
                    else:
                        if C == 0: candidate = c
                        elif D == 0: candidate = d
                        s = _parameter(candidate, a, tangent)
                        if not 0. < s < angle:
                            _fail('Interior intersection angle is not resolvable without snapping.')
                    event(s, owner)
    # Only equal represented parameters are united. Close distinct roots retain
    # their interval; an unrepresentable interval is explicitly refused below.
    groups = []
    for value, boundary in sorted(events, key=lambda row: row[0]):
        if groups and value == groups[-1][0]:
            previous, keys = groups[-1]
            selected = angle if value == angle else previous
            groups[-1] = (selected, keys | boundary)
        else:
            groups.append((value, boundary))
    queries = []
    for i, (value, boundary) in enumerate(groups):
        if boundary:
            queries.append((value, value, boundary))
        if i+1 < len(groups):
            following = groups[i+1][0]
            middle = value+(following-value)/2
            if not value < middle < following:
                _fail('Distinct arc intersections have no representable interior.')
            coincident = {owner for lo, hi, owner in overlaps if lo < middle < hi}
            queries.append((value, following, coincident))
    midpoints = np.asarray([lo+(hi-lo)/2 for lo, hi, _ in queries])
    directions = np.cos(midpoints)[:, None]*a+np.sin(midpoints)[:, None]*tangent
    return angle, queries, directions


def crust_intervals(atlas, structure, *, budget=None, cancel=None):
    """Return frozen angular intervals and contacts against actual S3 polygons.

    The native classifier is called at each analytically partitioned interior,
    and at contacts. Case precedence resolves definite interiors. On a boundary,
    all possible winning columns survive; no fixed-side tie-break is introduced.
    Inherited line corridors are intentionally outside this function's contract.
    Returned small records become caller-owned after the operation's reservation.
    """
    from atlas_tectonics import SphericalAtlas, SphericalGeometry, PrecursorState
    from atlas_tectonics.geological_domain import GeologicalDomain
    from atlas_tectonics.geometry import _check_cancel
    from atlas_tectonics.resources import select_budget

    source_hash(); _check_cancel(cancel)
    state = getattr(structure, 'state', structure)
    if type(atlas) is not SphericalAtlas or type(state) is not PrecursorState:
        _fail('Native spherical atlas and geological precursor required.')
    case = state.case
    if (type(case.topology) is not GeologicalDomain or not case.topology.full_sphere
            or case.topology.sphere != atlas.sphere):
        _fail('Plate atlas and full-sphere structure must share their actual frame and radius.')
    provinces = {p.province_id: p for p in case.provinces}
    order = case.precedence.province_order
    rank = {name: i for i, name in enumerate(order)}
    selected = set()
    for province in case.provinces:
        if province.selector.kind not in ('domain', 'geometry'):
            _fail('Initial crust must use domain or spherical geometry selectors.')
        if province.selector.kind == 'geometry':
            selected.update(province.selector.keys)
    geometries = {g.key: g.geometry for g in case.geometries if g.key in selected}
    if set(geometries) != selected:
        _fail('Crust selector lacks its native geometry.')
    for geometry in geometries.values():
        if (type(geometry) is not SphericalGeometry
                or geometry.kind not in ('Polygon', 'MultiPolygon')
                or geometry.chart.sphere != atlas.sphere):
            _fail('Crust selectors require spherical polygons in the actual shared frame.')
    count = sum(len(g._segments_start)//24 for g in geometries.values())
    resource = select_budget(budget)
    output = []
    # Segment preparation is linear in the small polygon inventory. Cross/dot
    # candidates and native queries are processed one atlas edge at a time.
    with ExitStack() as leases:
        leases.enter_context(resource.reserve(512*count+65536, category='crust-arc-work'))
        starts, ends, normals, tangents, lengths, owners = [], [], [], [], [], []
        for key, geometry in sorted(geometries.items()):
            _check_cancel(cancel)
            c = np.frombuffer(geometry._segments_start, dtype='f8').reshape(-1, 3)
            d = np.frombuffer(geometry._segments_end, dtype='f8').reshape(-1, 3)
            for first, last in zip(c, d):
                angle, normal, tangent = _arc_frame(first, last)
                starts.append(first); ends.append(last); normals.append(normal)
                tangents.append(tangent); lengths.append(angle); owners.append(key)
        starts = np.asarray(starts).reshape(-1, 3); ends = np.asarray(ends).reshape(-1, 3)
        normals = np.asarray(normals).reshape(-1, 3)
        tangents = np.asarray(tangents).reshape(-1, 3); lengths = np.asarray(lengths)
        vertices = atlas.vertex_directions
        for index in atlas.interplate_edges:
            _check_cancel(cancel)
            a, b = vertices[atlas.edge_vertices[index]]
            angle, queries, directions = _edge_partition(
                a, b, starts, ends, normals, tangents, lengths, owners)
            classifications = {key: geometry.classify(directions, budget=resource, cancel=cancel)
                               for key, geometry in geometries.items()}
            leases.enter_context(resource.reserve(256*len(queries), category='crust-arc-results'))
            for j, (low, high, boundary) in enumerate(queries):
                if low < high and any(int(codes[j]) == 0 and key not in boundary
                                      for key, codes in classifications.items()):
                    _fail('Arc interior is inside a native boundary uncertainty band without a certified overlap.')
                inside, uncertain = [], []
                for name in order[:-1]:
                    selector = provinces[name].selector
                    codes = [0 if key in boundary else int(classifications[key][j])
                             for key in selector.keys]
                    if 1 in codes:
                        inside.append(name)
                    elif 0 in codes:
                        uncertain.append(name)
                definite = case.resolve_provinces(tuple(inside)).province_id
                possible = {definite} | {name for name in uncertain if rank[name] < rank[definite]}
                columns = tuple(dict.fromkeys(provinces[name].column_id
                                  for name in order if name in possible))
                output.append(ArcCrustInterval(int(index), float(low/angle),
                                              float(high/angle), columns))
        _check_cancel(cancel); source_hash()
        return tuple(output)
