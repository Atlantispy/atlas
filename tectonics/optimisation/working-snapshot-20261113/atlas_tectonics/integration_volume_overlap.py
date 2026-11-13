"""Exact convex-polyhedral overlap for placed Cartesian material cells.

This is a measure/remap building block, not a material transfer or global clock.
It never approximates a curved shell. Optional angular clipping is admitted only
after the entire recipient box is proved inside the supplied radial layer.
All plane predicates, vertices and volume determinants use rational arithmetic.
No numerical tolerance, snapping, convex-hull filling or sliver deletion occurs.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations
import hashlib
import json
import math
import weakref

from . import integration_volume as V
from .resources import select_budget


SCHEMA = 'atlas.exact-cell-overlap.v1'
METHOD = 'integer-halfspace-vertices-and-oriented-determinants-v1'


class OverlapError(V.VolumeError):
    """Invalid overlap request or an unsupported curved intersection."""


def _dot(a, b):
    return sum((x*y for x, y in zip(a, b)), Fraction(0))


def _cross(a, b):
    return a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]


def _minus(a, b):
    return tuple(x-y for x, y in zip(a, b))


def _plane(normal, limit):
    """Canonical integers for normal.x <= limit; never reverse its sense."""
    values = tuple(map(Fraction, (*normal, limit)))
    multiple = math.lcm(*(v.denominator for v in values))
    integers = tuple(v.numerator*(multiple//v.denominator) for v in values)
    divisor = math.gcd(*integers)
    if not divisor or not any(integers[:3]):
        raise OverlapError('a supporting plane requires a nonzero normal')
    return tuple(v//divisor for v in integers)


def _box_planes(cell):
    # Columns of B are exactly orthonormal, including reflected frames.
    # B^T(x-origin) is the actual local point, not an enclosing AABB.
    planes = []
    for j in range(3):
        normal = tuple(cell.basis[i][j] for i in range(3))
        offset = _dot(normal, cell.origin_m)
        planes.append(_plane(normal, cell.upper_m[j]+offset))
        planes.append(_plane(tuple(-v for v in normal), -cell.lower_m[j]-offset))
    return planes


def _vertex(a, b, c):
    bc, ca, ab = _cross(b[:3], c[:3]), _cross(c[:3], a[:3]), _cross(a[:3], b[:3])
    determinant = sum(a[j]*bc[j] for j in range(3))
    if determinant == 0:
        return None
    return tuple(Fraction(a[3]*bc[j]+b[3]*ca[j]+c[3]*ab[j], determinant) for j in range(3))


def _dimension(vertices):
    if not vertices:
        return -1
    origin = vertices[0]
    vectors = tuple(_minus(v, origin) for v in vertices[1:])
    first = next((v for v in vectors if any(v)), None)
    if first is None:
        return 0
    normal = next((_cross(first, v) for v in vectors if any(_cross(first, v))), None)
    if normal is None:
        return 1
    return 3 if any(_dot(normal, v) != 0 for v in vectors) else 2


def _face(vertices, indices, normal):
    """Exact 2D monotone hull on an ALREADY PROVED supporting plane.

    This orders one convex-polyhedron face, not the input material union. The
    coordinate projection is nonsingular because its omitted normal is nonzero.
    Collinear face vertices contribute no separate triangles or volume.
    """
    omitted = max(range(3), key=lambda j: abs(normal[j]))
    axes = tuple(j for j in range(3) if j != omitted)
    ordered = sorted(indices, key=lambda i: tuple(vertices[i][j] for j in axes))

    def turn(i, j, k):
        p, q, r = vertices[i], vertices[j], vertices[k]
        x, y = axes
        return (q[x]-p[x])*(r[y]-p[y])-(q[y]-p[y])*(r[x]-p[x])

    def half(sequence):
        result = []
        for i in sequence:
            while len(result) > 1 and turn(result[-2], result[-1], i) <= 0:
                result.pop()
            result.append(i)
        return result

    lower, upper = half(ordered), half(ordered[::-1])
    ring = lower[:-1]+upper[:-1]
    if len(ring) < 3:
        return None
    orientation = _dot(normal, _cross(_minus(vertices[ring[1]], vertices[ring[0]]),
                                      _minus(vertices[ring[2]], vertices[ring[0]])))
    if orientation == 0:
        raise OverlapError('degenerate supporting face after exact hull ordering')
    if orientation < 0:
        ring.reverse()
    start = ring.index(min(ring))
    return tuple(ring[start:]+ring[:start])


def _encoded(value):
    value = Fraction(value)
    return [hex(value.numerator), hex(value.denominator)]


def _retain(result, values, links, resource):
    # Account newly retained exact output, not caller-owned input geometry.
    # Python object headers and four copies of integer payload are conservative
    # allowances; the active arithmetic reservation covers their construction.
    count = 4096+256*len(values)+32*links+4*sum((V._bits(v)+7)//8 for v in values)
    lease = resource.reserve(count, category='i03-volume-overlap-retained')
    lease.__enter__()
    try:
        weakref.finalize(result, lease.__exit__, None, None, None)
    except BaseException:
        lease.__exit__(None, None, None)
        raise
    return result


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class PolyhedralOverlap:
    """An issued immutable exact measure, not authority to debit either source.

    Zero volume retains dimension -1/0/1/2 for empty/point/edge/face contact.
    Faces exist only for positive-volume intersections and have outward winding.
    Report identities bind the ordered donor/recipient and optional shell/cone.
    A future importer must reproduce this operation, not trust copied measures.
    """
    source_cell_id: str
    recipient_cell_id: str
    radial_layer_id: object
    cone_id: object
    volume_m3: Fraction
    dimension: int
    vertices_m: tuple
    faces: tuple
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('PolyhedralOverlap is issued by intersect_cells()')

    def record(self):
        values = (self.volume_m3, *(v for p in self.vertices_m for v in p))
        with V._work(values, self._resource):
            return dict(schema=SCHEMA, method=METHOD, source_cell_id=self.source_cell_id,
                recipient_cell_id=self.recipient_cell_id, radial_layer_id=self.radial_layer_id,
                cone_id=self.cone_id, volume_m3=_encoded(self.volume_m3), dimension=self.dimension,
                vertices_m=[[ _encoded(v) for v in p] for p in self.vertices_m],
                faces=[list(face) for face in self.faces], number_encoding='rational-hex-v1',
                scope='exact polyhedral measure only; no source debit, field average or clock advancement')

    @property
    def overlap_id(self):
        return hashlib.sha256(json.dumps(self.record(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def intersect_cells(source, recipient, *, radial_layer=None, cone_vertices=None, budget=None):
    """Measure source box intersect recipient box, optionally intersect cone.

    With a cone, a typed RadialLayer is mandatory and the WHOLE recipient must
    lie between its inner/outer radii. Thus curved surfaces do not cut the
    resulting polyhedron. A radial layer without a cone provides the same
    radial certificate. No inference is made from corner-only inner radii.

    Integer plane triples enumerate the vertices of the bounded intersection.
    All halfspaces test each candidate exactly. Actual supporting faces are
    ordered and triangulated; their signed tetrahedral determinants give volume.
    The budget separately admits rational workspace and O(P^4) predicate work;
    this bounded small-overlap kernel is not a claim of bulk remap performance.
    """
    if type(source) is not V.CartesianCell or type(recipient) is not V.CartesianCell:
        raise OverlapError('two typed exact CartesianCell geometries are required')
    if radial_layer is not None and type(radial_layer) is not V.RadialLayer:
        raise OverlapError('radial support must be a typed RadialLayer')
    if cone_vertices is not None and radial_layer is None:
        raise OverlapError('angular source clipping requires a proved common radial layer')
    resource = select_budget(budget) if budget is not None else source._resource
    cone = (None if cone_vertices is None else
            V.convex_cone_union((cone_vertices,), budget=resource))
    values = (*source._geometry(), *recipient._geometry(),
              *(() if radial_layer is None else radial_layer._geometry()),
              *(v for p in (cone or ()) for v in p))
    with V._work(values, resource):
        if radial_layer is not None:
            minimum, maximum = recipient._radial_bounds()
            radius, top, bottom = radial_layer._geometry()
            if minimum < (radius-bottom)**2 or maximum > (radius-top)**2:
                raise OverlapError('whole recipient is not inside the radial layer; curved shell clipping is unsupported')
        planes = _box_planes(source)+_box_planes(recipient)
        if cone is not None:
            planes.extend(_plane(tuple(-v for v in _cross(a, b)), 0)
                          for a, b in zip(cone, cone[1:]+cone[:1]))
        planes = tuple(sorted(set(planes)))
        count = len(planes)
        bits = max(max(1, abs(v).bit_length()) for p in planes for v in p)
        # Cramer's numerators/denominators use products of three integer plane
        # coefficients. 64*b covers arithmetic/GCD temporaries beyond the
        # 6*b+O(1) retained coordinate size. A bounded convex 3-polytope with P
        # supporting planes has <=2P-4 vertices and <=6P-12 face-vertex links;
        # lower-dimensional bounded contacts require no more storage.
        arithmetic = 65536+(64*count+64)*(256+8*bits)
        # Byte-equivalent work admission, deliberately not an RSS estimate.
        # Also bounds quadratic hull sorting/face predicates under this cost.
        work = 256*math.comb(count, 3)*count
        with resource.reserve(arithmetic+work, category='i03-volume-overlap'):
            found = set()
            for a, b, c in combinations(planes, 3):
                point = _vertex(a, b, c)
                if point is not None and all(_dot(p[:3], point) <= p[3] for p in planes):
                    found.add(point)
            vertices = tuple(sorted(found))
            dimension, faces = _dimension(vertices), []
            volume = Fraction(0)
            if dimension == 3:
                for plane in planes:
                    indices = tuple(i for i, point in enumerate(vertices) if _dot(plane[:3], point) == plane[3])
                    if len(indices) >= 3:
                        face = _face(vertices, indices, plane[:3])
                        if face is not None:
                            faces.append(face)
                faces = tuple(sorted(set(faces)))
                # A vertex mean is inside this convex body. Each outward face
                # pyramid must have nonnegative signed volume independently.
                centre = tuple(sum(p[j] for p in vertices)/len(vertices) for j in range(3))
                for face in faces:
                    a = _minus(vertices[face[0]], centre)
                    for i in range(1, len(face)-1):
                        six = _dot(a, _cross(_minus(vertices[face[i]], centre),
                                            _minus(vertices[face[i+1]], centre)))
                        if six < 0:
                            raise OverlapError('supporting face orientation contradicts convex volume')
                        volume += six/6
                if volume <= 0 or volume > min(source.volume_m3, recipient.volume_m3):
                    raise OverlapError('exact intersection violates positive bounded volume')
            else:
                faces = ()
            cone_id = (None if cone is None else hashlib.sha256(json.dumps(
                [[_encoded(v) for v in p] for p in cone], separators=(',', ':')).encode()).hexdigest())
            result = object.__new__(PolyhedralOverlap)
            for name, value in dict(source_cell_id=source.cell_id, recipient_cell_id=recipient.cell_id,
                    radial_layer_id=None if radial_layer is None else radial_layer.layer_id,
                    cone_id=cone_id, volume_m3=volume, dimension=dimension, vertices_m=vertices,
                    faces=faces, _resource=resource).items():
                object.__setattr__(result, name, value)
            return _retain(result, (volume, *(v for p in vertices for v in p)),
                           sum(map(len, faces)), resource)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class UniformTransfer:
    """Exact one-donor extensive allocation, with an explicit unmapped balance.

    This contains no evolving field, ownership mutation, averaging of endpoint
    values, or transit-history reconstruction. A transaction owner must bind
    both account identifiers to one declared source time and apply deltas once.
    Independent overlapping recipients must NOT be summed as a partition.
    """
    source_id: str
    target_id: str
    overlap: PolyhedralOverlap
    source_volume_m3: Fraction
    coefficient: Fraction
    unmapped_volume_m3: Fraction
    source_stocks: tuple
    source_delta: tuple
    target_delta: tuple
    source_remainder: tuple
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('UniformTransfer is issued by transfer_uniform()')

    def record(self):
        values = (self.source_volume_m3, self.coefficient, self.unmapped_volume_m3,
                  *self.source_stocks, *self.source_delta, *self.target_delta, *self.source_remainder)
        with V._work(values, self._resource):
            return dict(schema='atlas.exact-uniform-cell-transfer.v1', method=METHOD,
                source_id=self.source_id, target_id=self.target_id, overlap_id=self.overlap.overlap_id,
                source_cell_id=self.overlap.source_cell_id, recipient_cell_id=self.overlap.recipient_cell_id,
                source_volume_m3=_encoded(self.source_volume_m3), coefficient=_encoded(self.coefficient),
                unmapped_volume_m3=_encoded(self.unmapped_volume_m3),
                source_stocks=list(map(_encoded, self.source_stocks)),
                source_delta=list(map(_encoded, self.source_delta)),
                target_delta=list(map(_encoded, self.target_delta)),
                source_remainder=list(map(_encoded, self.source_remainder)),
                number_encoding='rational-hex-v1',
                scope='uniform whole-source-box allocation; no ownership mutation or clock advancement')

    @property
    def transfer_id(self):
        return hashlib.sha256(json.dumps(self.record(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def transfer_uniform(source, recipient, stocks, *, source_id, target_id,
                     radial_layer=None, cone_vertices=None, budget=None):
    """Allocate explicit extensive scalars of one homogeneous physical box.

    Each stock describes the ENTIRE source CartesianCell with uniform volume
    density. Int/Fraction scalars are mandatory; no implicit rounded conversion
    or temperature-to-heat inference occurs. Signed scalars are permitted (for
    example reference-relative enthalpy); this is not a positivity model.

    f=|source intersect recipient [intersect cone]|/|source|, delta=f*stock,
    remainder=(1-f)*stock. No row is rescaled to force a full transfer. Even
    with cone clipping, the denominator remains the whole declared source box;
    supplying stock for only a cut-box region would violate this contract.
    """
    if type(source) is not V.CartesianCell or type(recipient) is not V.CartesianCell:
        raise OverlapError('two typed exact CartesianCell geometries are required')
    if type(stocks) is not tuple or not stocks or any(type(q) not in (int, Fraction) for q in stocks):
        raise OverlapError('stocks must be a nonempty tuple of exact int/Fraction extensive scalars')
    if any(type(key) is not str or not key for key in (source_id, target_id)) or source_id == target_id:
        raise OverlapError('distinct nonempty source and target account identifiers are required')
    resource = select_budget(budget) if budget is not None else source._resource
    with resource.reserve(65536+8*(len(source_id)+len(target_id))+1024*len(stocks),
                          category='i03-volume-transfer'):
        with V._work(stocks, resource) as exact:
            overlap = intersect_cells(source, recipient, radial_layer=radial_layer,
                                      cone_vertices=cone_vertices, budget=resource)
            with V._work((*exact, overlap.volume_m3, *source._geometry()), resource):
                total = source.volume_m3
                fraction = overlap.volume_m3/total
                target_delta = tuple(q*fraction for q in exact)
                source_delta = tuple(-q for q in target_delta)
                remainder = tuple(q-d for q, d in zip(exact, target_delta))
                result = object.__new__(UniformTransfer)
                for name, value in dict(source_id=source_id, target_id=target_id, overlap=overlap,
                        source_volume_m3=total, coefficient=fraction, unmapped_volume_m3=total-overlap.volume_m3,
                        source_stocks=exact, source_delta=source_delta, target_delta=target_delta,
                        source_remainder=remainder, _resource=resource).items():
                    object.__setattr__(result, name, value)
                return _retain(result, (total, fraction, total-overlap.volume_m3,
                    *exact, *source_delta, *target_delta, *remainder),
                    len(source_id)+len(target_id), resource)
