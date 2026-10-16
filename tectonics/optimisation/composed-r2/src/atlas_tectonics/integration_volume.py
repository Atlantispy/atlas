"""Physical radial-shell measures and exact pure Cartesian-cell predicates.

Surface area is measured at the declared reference radius R. A reference prism
uses A*(b-a); a physical radial shell uses A*integral_a^b (1-z/R)^2 dz. These
are different source conventions, not alternative rounding formulae. This
module does not convert existing inventories or assign material ownership.

Cartesian frames are exactly orthogonal rational isometries. A rounded ENU
matrix is not silently orthogonalised. Mixed/cut-cell volumes are not inferred.
All predicates and integrals below are rational; no scientific tolerance is
introduced. Workspace admission is conservative accounting, not an RSS limit.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, InitVar
from fractions import Fraction
from itertools import product
import hashlib
import json
import math

from ._validation import TectonicsError
from .resources import select_budget

REFERENCE_PRISM = 'reference_prism'
PHYSICAL_RADIAL_SHELL = 'physical_radial_shell'
_IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


class VolumeError(TectonicsError):
    """An invalid or unsupported physical volume declaration."""


def _bits(value):
    if type(value) is int:
        return max(1, value.bit_length())
    if type(value) is Fraction:
        return max(1, value.numerator.bit_length()+value.denominator.bit_length())
    if type(value) is float and math.isfinite(value):
        # Binary64 numerator and denominator before conversion, including a
        # subnormal. A fixed upper bound avoids allocating them before admission.
        return 2150
    raise VolumeError('finite int, float or Fraction required; booleans and implicit numeric coercions are refused')


@contextmanager
def _work(values, budget, *, pairs=0):
    bits = sum(_bits(v) for v in values)
    # Includes rational products/GCD temporaries, encoding and object overhead.
    # The pair allowance also bounds the explicit O(n^2) convex-cone validation;
    # callers cannot turn a small byte budget into unbounded predicate work.
    with select_budget(budget).reserve(65536+128*bits+256*len(values)+256*pairs,
                                       category='i03-physical-volume'):
        yield tuple(Fraction(v) for v in values)


def _triple(value, name):
    if type(value) not in (tuple, list) or len(value) != 3:
        raise VolumeError(name+' requires an explicit three-component sequence')
    return tuple(value)


def _encoded(value):
    # Hex avoids any process-wide decimal integer-string limit change.
    return [hex(value.numerator), hex(value.denominator)]


def _identity(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RadialLayer:
    """One physical shell interval, with area referenced to ``radius_m``.

    Inputs retain their exact represented values, including binary64 inputs.
    The constructor budget is also used by property evaluations. This immutable
    geometry does not claim its caller-supplied surface area is an exact solid
    angle measure, nor that a legacy reference-prism inventory funds it.
    """
    radius_m: Fraction
    top_depth_m: Fraction
    bottom_depth_m: Fraction
    budget: InitVar[object] = field(default=None, kw_only=True)
    _resource: object = field(init=False, repr=False, compare=False)

    def __post_init__(self, budget):
        resource = select_budget(budget)
        with _work((self.radius_m, self.top_depth_m, self.bottom_depth_m), resource) as values:
            radius, top, bottom = values
            if not 0 <= top < bottom <= radius:
                raise VolumeError('a physical radial layer requires 0 <= top < bottom <= positive radius')
            for name, value in zip(('radius_m', 'top_depth_m', 'bottom_depth_m'), values):
                object.__setattr__(self, name, value)
        object.__setattr__(self, '_resource', resource)

    @property
    def convention(self):
        return PHYSICAL_RADIAL_SHELL

    @property
    def thickness_m(self):
        with _work((self.top_depth_m, self.bottom_depth_m), self._resource):
            return self.bottom_depth_m-self.top_depth_m

    @property
    def top_radius_m(self):
        with _work((self.radius_m, self.top_depth_m), self._resource):
            return self.radius_m-self.top_depth_m

    @property
    def bottom_radius_m(self):
        with _work((self.radius_m, self.bottom_depth_m), self._resource):
            return self.radius_m-self.bottom_depth_m

    def _geometry(self):
        return self.radius_m, self.top_depth_m, self.bottom_depth_m

    def _factor(self):
        radius, top, bottom = self._geometry()
        h, rt, rb = bottom-top, radius-top, radius-bottom
        return h*(rt*rt+rt*rb+rb*rb)/(3*radius*radius)

    @property
    def volume_per_area_m(self):
        """Exact integral of (1-z/R)^2, using only positive radial products."""
        with _work(self._geometry(), self._resource):
            return self._factor()

    def volume_m3(self, surface_area_m2):
        with _work((*self._geometry(), surface_area_m2), self._resource) as values:
            area = values[-1]
            if area < 0:
                raise VolumeError('reference-surface area must be nonnegative')
            return area*self._factor()

    def heat_capacity_j_per_k(self, surface_area_m2, density_kg_m3, heat_capacity_j_kg_k):
        """Constant physical rho*Cp integrated over the shell, not a prism."""
        with _work((*self._geometry(), surface_area_m2, density_kg_m3, heat_capacity_j_kg_k),
                   self._resource) as values:
            area, density, capacity = values[-3:]
            if area < 0 or density <= 0 or capacity <= 0:
                raise VolumeError('nonnegative area and positive density/heat capacity required')
            return area*density*capacity*self._factor()

    def linear_weights_m(self):
        """Top/bottom weights for a scalar linear in depth over this layer.

        Their sum is V/A. These positive factored polynomials avoid subtraction
        of near-equal powers at thin depth intervals.
        """
        with _work(self._geometry(), self._resource):
            radius, top, bottom = self._geometry()
            h, rt, rb = bottom-top, radius-top, radius-bottom
            common = h/(12*radius*radius)
            return common*(3*rt*rt+2*rt*rb+rb*rb), common*(rt*rt+2*rt*rb+3*rb*rb)

    def integrate_linear_per_area(self, top_value, bottom_value):
        """Integral_a^b scalar(z)*(1-z/R)^2 dz; signed scalars are allowed."""
        with _work((*self._geometry(), top_value, bottom_value), self._resource) as values:
            wt, wb = self.linear_weights_m()
            return values[-2]*wt+values[-1]*wb

    @property
    def volume_centroid_radius_m(self):
        """Exact volume-weighted radius; node choice remains the solver's policy."""
        with _work(self._geometry(), self._resource):
            radius, top, bottom = self._geometry()
            rt, rb = radius-top, radius-bottom
            return 3*(rt+rb)*(rt*rt+rb*rb)/(4*(rt*rt+rt*rb+rb*rb))

    @property
    def volume_centroid_depth_m(self):
        with _work(self._geometry(), self._resource):
            return self.radius_m-self.volume_centroid_radius_m

    def radial_resistance_per_area_m2_k_w(self, conductivity_w_m_k):
        """R^2 * integral_a^b dz/[k*(R-z)^2], for positive constant k.

        Resistance is temperature difference divided by heat flux per area at
        the reference sphere. A layer reaching the centre has divergent point
        resistance and is refused; it is never replaced by a finite planar value.
        """
        with _work((*self._geometry(), conductivity_w_m_k), self._resource) as values:
            radius, top, bottom, conductivity = values
            if conductivity <= 0 or bottom == radius:
                raise VolumeError('radial point resistance requires positive conductivity and inner radius')
            return radius*radius*(bottom-top)/(conductivity*(radius-top)*(radius-bottom))

    def record(self):
        with _work(self._geometry(), self._resource):
            return dict(schema='atlas.physical-radial-layer.v1', convention=self.convention,
                        radius_m=_encoded(self.radius_m), top_depth_m=_encoded(self.top_depth_m),
                        bottom_depth_m=_encoded(self.bottom_depth_m), number_encoding='rational-hex-v1')

    @property
    def layer_id(self):
        return _identity(self.record())


@dataclass(frozen=True, slots=True)
class CartesianCell:
    """A physical box under an exact rational affine isometry.

    Basis columns are local axes in sphere-centred Cartesian XYZ; origin is in
    that same frame. This geometry is not authenticated to a native plan or
    material source: the regional owner must bind and reproduce those identities.
    """
    lower_m: tuple
    upper_m: tuple
    origin_m: tuple = (0, 0, 0)
    basis: tuple = _IDENTITY
    budget: InitVar[object] = field(default=None, kw_only=True)
    _resource: object = field(init=False, repr=False, compare=False)

    def __post_init__(self, budget):
        lower, upper, origin = (_triple(v, name) for v, name in
                                 ((self.lower_m, 'lower bound'), (self.upper_m, 'upper bound'),
                                  (self.origin_m, 'Cartesian origin')))
        rows = _triple(self.basis, 'basis rows')
        rows = tuple(_triple(row, 'basis row') for row in rows)
        resource = select_budget(budget)
        with _work((*lower, *upper, *origin, *(v for row in rows for v in row)), resource) as q:
            lower, upper, origin = q[:3], q[3:6], q[6:9]
            rows = tuple(tuple(q[9+3*i:12+3*i]) for i in range(3))
            if any(a >= b for a, b in zip(lower, upper)):
                raise VolumeError('each cell upper bound must be strictly above its lower bound')
            if any(sum(rows[k][i]*rows[k][j] for k in range(3)) != int(i == j)
                   for i in range(3) for j in range(3)):
                raise VolumeError('Cartesian basis must be exactly orthogonal; rounded frames are not repaired')
            for name, value in (('lower_m', lower), ('upper_m', upper), ('origin_m', origin), ('basis', rows)):
                object.__setattr__(self, name, value)
        object.__setattr__(self, '_resource', resource)

    def _geometry(self):
        return (*self.lower_m, *self.upper_m, *self.origin_m, *(v for row in self.basis for v in row))

    def _bounds(self):
        """Axis-aligned bounding box only, NOT the rotated material support."""
        vertices = self._vertices()
        return (tuple(min(p[j] for p in vertices) for j in range(3)),
                tuple(max(p[j] for p in vertices) for j in range(3)))

    def _vertices(self):
        return tuple(sorted(tuple(o+sum(b*q for b, q in zip(row, point))
                                  for o, row in zip(self.origin_m, self.basis))
                            for point in product(*zip(self.lower_m, self.upper_m))))

    def _radial_bounds(self):
        # Orthogonality makes |o+Bq|^2=|B^T o+q|^2. The nearest
        # point may be inside a face/edge/interior, not at a vertex.
        offset = tuple(sum(self.basis[k][j]*self.origin_m[k] for k in range(3))
                       for j in range(3))
        ends = tuple((a+o, b+o) for a, b, o in zip(self.lower_m, self.upper_m, offset))
        minimum = maximum = Fraction(0)
        a2 = b2 = None
        try:
            for a, b in ends:
                a2, b2 = a*a, b*b
                minimum += 0 if a <= 0 <= b else min(a2, b2)
                maximum += max(a2, b2)
                # Do not overlap the previous pair with the next axis's squares.
                a2 = b2 = None
            return minimum, maximum
        finally:
            # No new derived rational graph survives through an error frame.
            a2 = b2 = minimum = maximum = None

    @property
    def volume_m3(self):
        with _work(self._geometry(), self._resource):
            return math.prod(b-a for a, b in zip(self.lower_m, self.upper_m))

    @property
    def vertices_m(self):
        with _work(self._geometry(), self._resource):
            return self._vertices()

    @property
    def radial_bounds_squared_m2(self):
        """True min/max over the entire box, including a closest interior point."""
        with _work(self._geometry(), self._resource):
            return self._radial_bounds()

    def rotated(self, quaternion, *, budget=None):
        """Rotate the support about the sphere centre without growing its box.

        Uses the rational quaternion map Q(q)/|q|^2, exactly orthogonal even
        when q's stored binary64 norm is not precisely one. This defines the
        rotation of the represented quaternion, not a new time integration.
        """
        if type(quaternion) not in (tuple, list) or len(quaternion) != 4:
            raise VolumeError('rotation requires four explicit quaternion components')
        resource = self._resource if budget is None else select_budget(budget)
        with _work((*self._geometry(), *quaternion), resource) as values:
            w, x, y, z = values[-4:]
            norm = w*w+x*x+y*y+z*z
            if norm == 0:
                raise VolumeError('a zero quaternion does not define a rotation')
            matrix = tuple(tuple(v/norm for v in row) for row in (
                (w*w+x*x-y*y-z*z, 2*(x*y-w*z), 2*(x*z+w*y)),
                (2*(x*y+w*z), w*w-x*x+y*y-z*z, 2*(y*z-w*x)),
                (2*(x*z-w*y), 2*(y*z+w*x), w*w-x*x-y*y+z*z)))
            origin = tuple(sum(row[k]*self.origin_m[k] for k in range(3)) for row in matrix)
            basis = tuple(tuple(sum(row[k]*self.basis[k][j] for k in range(3)) for j in range(3))
                          for row in matrix)
            return CartesianCell(self.lower_m, self.upper_m, origin, basis, budget=resource)

    def record(self):
        with _work(self._geometry(), self._resource):
            legacy = all(v in (-1, 0, 1) for row in self.basis for v in row)
            return dict(schema='atlas.exact-cartesian-cell.v1' if legacy else 'atlas.exact-cartesian-cell.v2',
                        lower_m=list(map(_encoded, self.lower_m)),
                        upper_m=list(map(_encoded, self.upper_m)), origin_m=list(map(_encoded, self.origin_m)),
                        basis=[[(int(v) if legacy else _encoded(v)) for v in row] for row in self.basis],
                        number_encoding='rational-hex-v1',
                        frame_rule='basis columns are local axes in sphere-centred Cartesian XYZ')

    @classmethod
    def from_record(cls, record, *, budget=None):
        keys = {'schema', 'lower_m', 'upper_m', 'origin_m', 'basis', 'number_encoding', 'frame_rule'}
        if type(record) is not dict or set(record) != keys or record['schema'] not in (
                'atlas.exact-cartesian-cell.v1', 'atlas.exact-cartesian-cell.v2'):
            raise VolumeError('a canonical exact Cartesian cell record is required')
        groups = tuple(_triple(record[k], k) for k in ('lower_m', 'upper_m', 'origin_m'))
        rows = tuple(_triple(row, 'basis row') for row in _triple(record['basis'], 'basis'))
        fractions = tuple(v for group in groups for v in group)
        if record['schema'].endswith('.v2'):
            fractions += tuple(v for row in rows for v in row)
        if any(type(pair) is not list or len(pair) != 2 or
               any(type(text) is not str for text in pair) for pair in fractions):
            raise VolumeError('canonical rational-hex pairs are required')
        resource = select_budget(budget)
        # Charge decoding by encoded width before creating large integers.
        with resource.reserve(65536+128*sum(len(text) for pair in fractions for text in pair),
                              category='i03-physical-volume-restore'):
            try:
                def decode(pair):
                    numerator, denominator = (int(text, 16) for text in pair)
                    if denominator <= 0:
                        raise VolumeError('rational denominator must be positive')
                    return Fraction(numerator, denominator)
                bounds = tuple(tuple(decode(pair) for pair in group) for group in groups)
                basis = (tuple(tuple(decode(pair) for pair in row) for row in rows)
                         if record['schema'].endswith('.v2') else rows)
                cell = cls(*bounds, basis, budget=resource)
                if cell.record() != record:
                    raise VolumeError('noncanonical or changed Cartesian cell record')
                return cell
            except (ValueError, TypeError, ZeroDivisionError) as exc:
                if isinstance(exc, VolumeError):
                    raise
                raise VolumeError('malformed exact Cartesian cell record') from exc

    @property
    def cell_id(self):
        return _identity(self.record())


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]


def _cone_normals(points):
    normals = tuple(_cross(a, b) for a, b in zip(points, points[1:]+points[:1]))
    if any(not any(p) for p in points) or any(not any(n) for n in normals):
        raise VolumeError('zero rays and coincident/antipodal cone edges are invalid')
    if any(_dot(n, p) < 0 for n in normals for p in points):
        raise VolumeError('cone must be convex and counterclockwise')
    witness = tuple(sum(n[j] for n in normals) for j in range(3))
    if any(_dot(witness, p) <= 0 for p in points):
        raise VolumeError('cone must occupy a nondegenerate common open hemisphere')
    return normals


def convex_cone_union(cones, *, budget=None):
    """Prove a conforming union is exactly one convex cone; return its ring.

    The input cells must be convex, counterclockwise, and share entire edges
    with exactly opposite orientations. Positive ray rescaling is immaterial.
    Cancellation must leave one simple convex boundary, containing every input
    vertex. In its common open-hemisphere chart the positively oriented cells
    form a planar 2-chain whose boundary is that ring. Winding number therefore
    makes their coverage exactly one inside and zero outside: holes and overlaps
    cannot be hidden by taking a convex hull or testing only box vertices.

    This is intentionally not a general union algorithm. Nonconforming edge
    subdivisions/T-junctions, holes, gaps, repeated cells and nonconvex unions
    raise VolumeError. A caller may still certify its box in one original cell.
    The canonical immutable output can be reused for all boxes in this patch;
    this function does not change, merge or allocate the source material.
    """
    if type(cones) not in (tuple, list) or not cones:
        raise VolumeError('an explicit nonempty sequence of convex cones is required')
    resource = select_budget(budget)
    with resource.reserve(65536+256*len(cones), category='i03-volume-union'):
        if any(type(c) not in (tuple, list) or len(c) < 3 for c in cones):
            raise VolumeError('each convex cone needs at least three explicit vertices')
        count = sum(map(len, cones))
        # Bound retained edge/vertex tables and quadratic convexity/containment
        # work before copying rows; exact-rational arithmetic is charged below.
        with resource.reserve(65536+2048*count+256*count*count, category='i03-volume-union'):
            points = tuple(_triple(p, 'cone vertex') for c in cones for p in c)
            values = tuple(v for p in points for v in p)
            with _work(values, resource) as exact:
                canonical = []
                for i in range(count):
                    ray = exact[3*i:3*i+3]
                    if not any(ray):
                        raise VolumeError('zero rays are invalid')
                    scale = abs(next(v for v in ray if v))
                    canonical.append(tuple(v/scale for v in ray))
                edges, offset = set(), 0
                for cone in cones:
                    ring = tuple(canonical[offset:offset+len(cone)])
                    offset += len(cone)
                    _cone_normals(ring)
                    for edge in zip(ring, ring[1:]+ring[:1]):
                        if edge in edges:
                            raise VolumeError('repeated oriented edges or overlapping cell copies are unsupported')
                        edges.add(edge)
                boundary = tuple(e for e in edges if (e[1], e[0]) not in edges)
                outgoing, incoming = {}, set()
                for a, b in boundary:
                    if a in outgoing or b in incoming:
                        raise VolumeError('union boundary is not a simple conforming ring; T-junctions are unsupported')
                    outgoing[a] = b
                    incoming.add(b)
                if len(boundary) < 3 or set(outgoing) != incoming:
                    raise VolumeError('union requires one closed conforming outer ring')
                start = min(outgoing)
                ring, point = [], start
                while True:
                    ring.append(point)
                    point = outgoing[point]
                    if point == start:
                        break
                if len(ring) != len(boundary):
                    raise VolumeError('union has multiple boundaries: holes, gaps or disconnected cells are unsupported')
                ring = tuple(ring)
                normals = _cone_normals(ring)
                if any(_dot(n, p) < 0 for n in normals for p in canonical):
                    raise VolumeError('an input cell lies outside the proved convex union boundary')
                return ring


def contains_cartesian_cell(layer, cone_vertices, cell, *, budget=None):
    """Certify the WHOLE box in one actual convex radial patch/layer.

    Vertices must be ordered counterclockwise homogeneous directions in the
    same sphere-centred Cartesian frame as the cell. Exact boundary equality
    is admitted. False means this cell is not pure/contained; invalid cone or
    frame data raises VolumeError. A conforming convex union can first be proved
    with convex_cone_union; mere vertex membership in a union is not sufficient.
    """
    if type(layer) is not RadialLayer or type(cell) is not CartesianCell:
        raise VolumeError('typed radial-layer and Cartesian-cell geometry required')
    if type(cone_vertices) not in (tuple, list) or len(cone_vertices) < 3:
        raise VolumeError('a convex cone needs at least three explicit homogeneous vertices')
    count = len(cone_vertices)
    # Account the list/row traversal before copying user input.
    resource = select_budget(budget) if budget is not None else cell._resource
    with resource.reserve(65536+1024*count+256*count*count, category='i03-volume-cone'):
        points = tuple(_triple(p, 'cone vertex') for p in cone_vertices)
        values = (*layer._geometry(), *cell._geometry(), *(v for p in points for v in p))
        with _work(values, resource) as exact:
            points = tuple(tuple(exact[21+3*i:24+3*i]) for i in range(count))
            normals = _cone_normals(points)
            if any(_dot(n, p) < 0 for p in cell._vertices() for n in normals):
                return False
            minimum, maximum = cell._radial_bounds()
            radius, top, bottom = layer._geometry()
            return minimum >= (radius-bottom)**2 and maximum <= (radius-top)**2
