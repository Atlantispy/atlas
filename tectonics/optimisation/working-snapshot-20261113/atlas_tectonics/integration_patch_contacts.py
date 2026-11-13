"""Exact material contact topology for patch-column thermal exchange.

Within-face cell-union edges cancel before contact ownership is emitted. Across
faces the named network edge is the common parameterisation; independently
rounded world coordinates never decide material adjacency.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
from fractions import Fraction
from collections import defaultdict

import numpy as np

from . import integration_support as U
from . import integration_transfer as T
from .resources import select_budget


@dataclass(frozen=True)
class PatchContact:
    left_patch: str
    right_patch: str
    start_direction: tuple
    end_direction: tuple


def _plane(p, q):
    n = T._primitive(T._cross(p, q))
    return n if next(v for v in n if v) > 0 else tuple(-v for v in n)


def _parameter(u, v, point):
    """Exact projective minor-arc coordinate, or None outside the positive cone."""
    if T._dot(T._cross(u, v), point) != 0:
        return None
    for i, j in ((0, 1), (0, 2), (1, 2)):
        det = u[i]*v[j]-u[j]*v[i]
        if det:
            a = point[i]*v[j]-point[j]*v[i]
            b = u[i]*point[j]-u[j]*point[i]
            if a*det < 0 or b*det < 0 or a+b == 0:
                return None
            return Fraction(b, a+b)
    raise U.SupportError('a contact edge has no nondegenerate minor arc')


def _point(u, v, t):
    return T._primitive(tuple((t.denominator-t.numerator)*a+t.numerator*b for a, b in zip(u, v)))


def _side_intervals(patches, u, v, positive):
    normal, out = T._cross(u, v), []
    for patch in patches:
        for cell in patch.cells:
            lo, hi, coincident = Fraction(0), Fraction(1), False
            for p, q in zip(cell, cell[1:]+cell[:1]):
                n = T._cross(p, q)
                x, y = T._dot(n, u), T._dot(n, v)
                coincident |= x == y == 0
                if x < 0 and y < 0:
                    hi = lo
                    break
                if x < 0 <= y:
                    lo = max(lo, Fraction(-x, y-x))
                elif y < 0 <= x:
                    hi = min(hi, Fraction(x, x-y))
            inward = sum(T._sign(T._dot(normal, p)) for p in cell)
            if hi > lo and (not coincident or (inward > 0 if positive else inward < 0)):
                out.append((lo, hi, patch.patch_id))
    return out


def _world_arc(frame, p, q):
    values = T._turned(frame, U.directions((p, q)))
    if np.array_equal(values[0], values[1]) or np.linalg.norm(np.cross(*values)) == 0:
        raise U.SupportError('a positive exact material contact is not representable as a world arc')
    return tuple(map(float, values[0])), tuple(map(float, values[1]))


def _partition_plane(edges):
    """Minimal disjoint arcs of a cell-edge union, with signed owner counts.

    Every base arc is cut at EVERY endpoint on its supporting plane which lies
    on that arc. Thus nested/partly overlapping bases produce identical minimal
    intervals, not overlapping output intervals. Exact ray-pair deduplication
    happens before emitting even a cancelled or one-sided interval.
    """
    vertices = {p for edge in edges for p in edge[:2]}
    bases = {tuple(sorted((p, q))) for p, q, _, _ in edges}
    emitted = set()
    for u, v in sorted(bases):
        cuts = sorted({t for p in vertices if (t := _parameter(u, v, p)) is not None})
        for lo, hi in zip(cuts, cuts[1:]):
            p, q = _point(u, v, lo), _point(u, v, hi)
            identity = tuple(sorted((p, q)))
            if identity in emitted:
                continue
            emitted.add(identity)
            mid = _point(u, v, (lo+hi)/2)
            sides = defaultdict(int)
            for a, b, patch_id, sign in edges:
                if _parameter(a, b, mid) is not None:
                    sides[patch_id] += sign
            yield p, q, mid, {key: value for key, value in sides.items() if value}


def _named_edge_points(start, end, cuts):
    """One exact projective chart of the network's stored endpoint vectors.

    _integers scales the ENTIRE TWO-ROW array by one denominator; endpoints must
    not be primitive-reduced independently before evaluating the chord. The
    owner-side clipping uses the same paired-raw-vector convention. This is the
    named-edge gluing of the existing C10 copy contract, not a claim that rounded
    plate copies are exact rotations. Only the final world direction is rounded.
    """
    u, v = T._integers((start, end))
    points = {Fraction(0): tuple(map(float, start)), Fraction(1): tuple(map(float, end))}
    for cut in cuts:
        if cut not in points:
            points[cut] = tuple(map(float, U.directions((_point(u, v, cut),))[0]))
    return points


def contacts(sphere, *, budget=None):
    """Every positive-length patch interface, as disjoint world minor arcs.

    Candidate work is sparse by face and exact supporting plane, plus network
    neighbours. No all-world patch-pair comparison, geometric tolerance or snap.
    Repeated arc fragments are deduplicated only by their exact homogeneous rays.
    """
    network, support = sphere.network, U.required(sphere.material)
    with select_budget(budget).reserve(support.workspace_bytes(), category='patch-contact-index'):
        by_face, groups = defaultdict(list), defaultdict(list)
        for patch in support.patches:
            by_face[patch.face_id].append(patch)
            for cell in patch.cells:
                for p, q in zip(cell, cell[1:]+cell[:1]):
                    plane = _plane(p, q)
                    sign = T._sign(T._dot(plane, T._cross(p, q)))
                    groups[patch.face_id, plane].append((p, q, patch.patch_id, sign))
        # Charge the worst local interval-partition candidate work before looping;
        # this is an engineering admission bound, not a physical error allowance.
        work = 65536+256*sum(len(edges)**2 for edges in groups.values())
        with select_budget(budget).reserve(work, category='patch-contact-partition'):
            frames = dict(network._layout.frames)
            local_index = {name: i for i, name in enumerate(network._layout.names)}
            face_edges, directed = {}, {}
            for face in network.faces:
                local = network._local[network.plate_ids.index(face.plate_id)]
                edges = []
                for ring in (face.vertex_ids, *face.holes):
                    for a, b in zip(ring, ring[1:]+ring[:1]):
                        if (a, b) in directed:
                            raise U.SupportError('a directed network edge has two face owners')
                        directed[a, b] = face.face_id
                        edges.append(tuple(T._integers(local[[local_index[a], local_index[b]]])))
                face_edges[face.face_id] = edges
            result = []
            for (face_id, plane), edges in sorted(groups.items()):
                for p, q, mid, sides in _partition_plane(edges):
                    if not sides:  # exact cancellation of a cell-union fan edge
                        continue
                    if any(abs(value) != 1 for value in sides.values()):
                        raise U.SupportError('material cell-union edge has ambiguous same-side coverage')
                    if len(sides) == 1:
                        if not any(_parameter(a, b, mid) is not None for a, b in face_edges[face_id]):
                            raise U.SupportError('an internal material edge has missing neighbouring material')
                        continue  # handled once below through the named network edge
                    if len(sides) != 2 or sum(sides.values()) != 0:
                        raise U.SupportError('material contact has missing or overlapping sided ownership')
                    pair = tuple(sorted(sides))
                    a, b = _world_arc(frames[network.face_plate(face_id)], p, q)
                    result.append(PatchContact(*pair, a, b))
            vertex = dict(zip(network.vertex_ids, network.vertex_direction))
            for (start, end), left in sorted(directed.items()):
                right = directed.get((end, start))
                if right is None:
                    raise U.SupportError('the closed spherical material domain has an unpaired network edge')
                if left > right:
                    continue
                sides, cuts = [], {Fraction(0), Fraction(1)}
                for index, face in enumerate((left, right)):
                    plate = network.face_plate(face)
                    local = network._local[network.plate_ids.index(plate)]
                    u, v = T._integers(local[[local_index[start], local_index[end]]])
                    intervals = _side_intervals(by_face[face], u, v, index == 0)
                    sides.append(intervals)
                    cuts.update(t for lo, hi, _ in intervals for t in (lo, hi))
                ordered = sorted(cuts)
                points = _named_edge_points(vertex[start], vertex[end], ordered)
                for lo, hi in zip(ordered, ordered[1:]):
                    mid = (lo+hi)/2
                    pair = []
                    for intervals in sides:
                        found = {patch for low, high, patch in intervals if low < mid < high}
                        if len(found) != 1:
                            raise U.SupportError('network edge has missing or ambiguous exact patch coverage')
                        pair.append(next(iter(found)))
                    if points[lo] == points[hi] or np.linalg.norm(np.cross(points[lo], points[hi])) == 0:
                        raise U.SupportError('positive exact network contact is not representable as a world arc')
                    result.append(PatchContact(*pair, points[lo], points[hi]))
            return tuple(result)
