"""Exact sufficient endpoint cone/voxel zero-volume certificate.

Never a material debit, wall/flux certificate, approximate sign decision or
universal zero-volume solver. Unsupported or inconclusive queries decline.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from itertools import combinations

from . import integration_differential_geometry as G

MAX_LITERALS = 32
MAX_TRIPLES = 128
ORDERS = (2, 4, 8, 16)


def _dot(a, b):
    return sum((x*y for x, y in zip(a, b)), Q(0))


def _cross(a, b):
    return tuple(a[(i+1) % 3]*b[(i+2) % 3]-a[(i+2) % 3]*b[(i+1) % 3]
                 for i in range(3))


def _series(s, order, shift, arena):
    """Consecutive alternating partial sums for cos (0) or sinc (1)."""
    total = term = Q(1)
    for k in range(1, order+2):
        with G.V._work((s, total, term), arena.resource):
            arena.work(32)
            term = -term*s/((2*k-1+shift)*(2*k+shift))
            previous, total = total, total+term
    return min(previous, total), max(previous, total)


def projection_bounds(u, theta, g, arena, *, order=8):
    """Enclose u.R(theta).g exactly; None declines |theta| > 1.

    Rodrigues gives A+B*cos(sqrt(s))+D*sinc(sqrt(s)), s=theta.theta.
    For 0<=s<=1 the alternating terms decrease, so consecutive sums bound
    each scalar function. Coefficient signs are handled before addition.
    """
    if type(order) is not int or not 0 <= order <= 16:
        raise ValueError('order must be an integer from 0 to 16')
    if any(len(v) != 3 for v in (u, theta, g)):
        raise ValueError('three-component vectors required')
    if any(type(x) not in (int, Q) for v in (u, theta, g) for x in v):
        raise ValueError('exact int/Fraction operands required')
    # One exact arithmetic route for this whole enclosure: the same rationals,
    # work units and admissions on either; only the two bounds leave it.
    kernel = G.B._resident()
    if (kernel is not G.B and _series is _reference[0] and _dot is _reference[1]
            and _cross is _reference[2]):
        return kernel._projection_bounds(u, theta, g, arena, order)
    with G.V._work((*u, *theta, *g), arena.resource):
        arena.work(96)
        s, value = _dot(theta, theta), _dot(u, g)
        if not s:
            return value, value
        if s > 1:
            return None
        A = _dot(u, theta)*_dot(theta, g)/s
        B, D = value-A, _dot(u, _cross(theta, g))
    with G.V._work((s, A, B, D), arena.resource):
        if B == D == 0:
            return A, A
        cosine, sinc = _series(s, order, 0, arena), _series(s, order, 1, arena)
        with G.V._work((A, B, D, *cosine, *sinc), arena.resource):
            arena.work(32)
            bc = sorted(B*x for x in cosine)
            ds = sorted(D*x for x in sinc)
            return A+bc[0]+ds[0], A+bc[1]+ds[1]


# The reference series and products as loaded; a wrapped or replaced one keeps
# every enclosure on this route (integration_volume_bounds._resident).
_reference = (_series, _dot, _cross)


def _encoded_scalars(value):
    """Collect exact input scalars for admission, not a second path decoder."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _encoded_scalars(item)
    elif isinstance(value, (list, tuple)):
        if len(value) == 2 and all(isinstance(x, str) and x.lstrip('-').startswith('0x') for x in value):
            yield G.W._decode(value)
        else:
            for item in value:
                yield from _encoded_scalars(item)


def plane_certificate(cell, literals, constraints, time, arena, *, detail=None):
    """Prove true rigid halfspace/voxel contact has zero endpoint volume.

    The signed nonzero normal n requires n.x >= 0. If all exact world-space
    vertices obey n.v <= 0, convexity confines the intersection to n.x = 0.
    Rotation preserves the normal's nonzero length, so that plane has zero
    3-D volume. Other literals and the shell can only restrict the set.
    Outward projections prove signs; small or unresolved values never fire.
    """
    if type(time) not in (int, Q):
        raise ValueError('exact endpoint time required')
    if not 1 <= len(literals) <= MAX_LITERALS:
        return None
    if any(type(sign) is not int or sign not in (-1, 1) for _, sign in literals):
        return None
    values = (*cell.origin_m, *cell.lower_m, *cell.upper_m,
              *(q for row in cell.basis for q in row))
    with G.V._work(values, arena.resource):
        arena.work(128)
        vertices = cell._vertices()
    for name, sign in literals:
        raw = constraints[name]
        scalars = tuple(_encoded_scalars(raw))
        with G.V._work((*scalars, time), arena.resource):
            arena.work(64)
            path = G._rigid_plane_path(raw)
            if path is None:
                continue
            normal, theta, omega = path
            endpoint = tuple(a+time*b for a, b in zip(theta, omega))
            signed = tuple(sign*x for x in normal)
            if not any(signed) or _dot(endpoint, endpoint) > 1:
                continue
        bounds, orders = [], []
        for vertex in vertices:
            pair = None
            for order in ORDERS:
                pair = projection_bounds(vertex, endpoint, signed, arena, order=order)
                if pair is None or pair[1] <= 0 or pair[0] > 0:
                    break
            if pair is None or pair[1] > 0:
                break
            bounds.append(pair)
            orders.append(order)
        if len(bounds) != len(vertices):
            continue
        with G.V._work((*signed, *endpoint, *(q for pair in bounds for q in pair)), arena.resource):
            arena.work(64)
            result = dict(kind='exact-rigid-plane-voxel-endpoint-zero-volume',
                literal=[name, sign], time_s=G._qtext(Q(time)),
                endpoint_rotation=G._store_vec(endpoint), signed_normal=G._store_vec(signed),
                vertex_projection_bounds=[list(map(G._qtext, pair)) for pair in bounds],
                series_orders=orders,
                scope='endpoint volume only; no interval flux or material debit')
        if detail is not None:
            detail['plane_voxel_zero_volume'] = result
        return result
    return None


def certificate(cell, literals, constraints, time, arena, *, detail=None):
    """Prove endpoint cone intersect voxel has zero volume, or return None.

    For independent signed normal rows m_i, signed adjugate columns g_j obey
    m_i.g_j=abs(det(m))*delta_ij. Their nonnegative cone is the three positive
    halfspaces. Projections >=0 plus max_voxel(u.x)<=0 restrict it to a plane.
    Extra literals and radial constraints can only restrict this intersection.
    """
    if type(time) not in (int, Q):
        raise ValueError('exact endpoint time required')
    if not 3 <= len(literals) <= MAX_LITERALS:
        return None
    values = (*cell.origin_m, *cell.lower_m, *cell.upper_m,
              *(q for row in cell.basis for q in row))
    with G.V._work(values, arena.resource):
        arena.work(128)
        vertices = cell._vertices()
        axes = []
        for j in range(3):
            for sign in (1, -1):
                u = tuple(sign*cell.basis[i][j] for i in range(3))
                maximum = max(_dot(u, p) for p in vertices)
                if any(u) and maximum <= 0:
                    axes.append((u, maximum))
    if not axes:
        return None
    groups = {}
    for name, sign in literals:
        if type(sign) is not int or sign not in (-1, 1):
            return None
        raw = constraints[name]
        scalars = tuple(_encoded_scalars(raw))
        with G.V._work((*scalars, time), arena.resource):
            arena.work(64)
            path = G._rigid_plane_path(raw)
            if path is None:
                continue
            normal, theta, omega = path
            endpoint = tuple(a+time*b for a, b in zip(theta, omega))
            if _dot(endpoint, endpoint) > 1:
                continue
            signed = tuple(sign*x for x in normal)
        groups.setdefault(endpoint, []).append((name, sign, signed))
    attempts = 0
    for theta, entries in groups.items():
        for triple in combinations(entries, 3):
            attempts += 1
            if attempts > MAX_TRIPLES:
                return None
            normals = tuple(row[2] for row in triple)
            with G.V._work((*theta, *(x for row in normals for x in row)), arena.resource):
                arena.work(128)
                delta = _dot(normals[0], _cross(normals[1], normals[2]))
                if not delta:
                    continue
                sign = 1 if delta > 0 else -1
                generators = tuple(tuple(sign*x for x in _cross(normals[(i+1) % 3], normals[(i+2) % 3]))
                                   for i in range(3))
            with G.V._work((delta, *(x for row in (*normals, *generators) for x in row)), arena.resource):
                arena.work(128)
                identity = tuple(tuple(_dot(m, g) for g in generators) for m in normals)
                expected = tuple(tuple(abs(delta) if i == j else Q(0) for j in range(3)) for i in range(3))
                if identity != expected:
                    raise ArithmeticError('signed adjugate identity failed')
            for u, maximum in axes:
                for order in ORDERS:
                    bounds = tuple(projection_bounds(u, theta, g, arena, order=order) for g in generators)
                    if any(pair is None for pair in bounds):
                        break
                    if all(low >= 0 for low, high in bounds):
                        with G.V._work((delta, maximum, *u, *theta,
                                        *(x for pair in bounds for x in pair)), arena.resource):
                            arena.work(64)
                            result = dict(kind='exact-rigid-normal-cone-voxel-endpoint-zero-volume',
                                literals=[[name, sign] for name, sign, _ in triple],
                                time_s=G._qtext(Q(time)), endpoint_rotation=G._store_vec(theta),
                                signed_normals=[G._store_vec(v) for v in normals],
                                determinant=G._qtext(delta), generators=[G._store_vec(v) for v in generators],
                                adjugate_identity=[[G._qtext(v) for v in row] for row in identity],
                                separator=G._store_vec(u), voxel_projection_maximum=G._qtext(maximum),
                                projection_bounds=[list(map(G._qtext, pair)) for pair in bounds],
                                series_order=order, triples_considered=attempts,
                                scope='endpoint volume only; no interval flux or material debit')
                        if detail is not None:
                            detail['cone_voxel_zero_volume'] = result
                        return result
                    if any(high < 0 for low, high in bounds):
                        break
    return None
