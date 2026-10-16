"""Certified rational enclosures of actual curved shell/CSG volume.

No curved surface is replaced in the material representation. Polyhedra are
only inner/outer INTEGRATION bounds, obtained from the exact identity
|x|^2 = 2*c.x-|c|^2 + |x-c|^2 on each rational subdivision box. An unresolved
interval remains explicit when the caller's subdivision limit is reached.
This module does not advance time, infer a wall flux or debit source stock.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from fractions import Fraction as Q
from itertools import product
import hashlib
import heapq
import json
import math
import sys
import weakref

from . import exact_arithmetic as X
from . import integration_volume as V
from . import integration_volume_overlap as O
from .resources import select_budget, WorkBudget, _GrowingLease, _GrowingPredicateLease


METHOD = 'quadratic-radius-rational-polyhedral-enclosure-v1'
# Ledger category of the GMP route's retained-coordinate surcharge. The
# reference route never charges it.
NATIVE_RETAINED = 'exact-native-retained'

# Local corner index is 4*x+2*y+z; upper/lower axis order matches _box_planes.
_BOX_RINGS = ((4, 6, 7, 5), (0, 1, 3, 2),
              (2, 3, 7, 6), (0, 4, 5, 1),
              (1, 5, 7, 3), (0, 2, 6, 4))


class _Arena:
    """One operation's retained scratch and cumulative finite-work admission."""
    def __init__(self, resource):
        self.resource, self.stack, self.work_units = resource, ExitStack(), 0
        self.lease = (_GrowingLease(resource) if type(resource) is WorkBudget and
                      'reserve' not in resource.__dict__ else None)
        self.predicate_lease = (_GrowingPredicateLease(resource) if
            resource.max_predicate_work_units is not None and type(resource) is WorkBudget and
            'reserve_predicate_work' not in resource.__dict__ else None)

    def __enter__(self):
        self.stack.__enter__()
        if self.lease is not None:
            self.stack.enter_context(self.lease)
        if self.predicate_lease is not None:
            self.stack.enter_context(self.predicate_lease)
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def work(self, count):
        # Explicit unit admission is independent of retained/temporary RAM.
        # Without opt-in, retain the original byte-equivalent allowance.
        if self.resource.max_predicate_work_units is not None:
            if self.predicate_lease is None:
                self.stack.enter_context(self.resource.reserve_predicate_work(count, category='curved-volume-work'))
            else:
                self.predicate_lease.add(count, category='curved-volume-work')
        elif self.lease is None:
            self.stack.enter_context(self.resource.reserve(32*count, category='curved-volume-work'))
        else:
            self.lease.add(32*count, category='curved-volume-work')
        self.work_units += count

    def keep(self, values, objects=0):
        self._retain(1024+128*len(values)+128*objects+4*sum((V._bits(v)+7)//8 for v in values))

    def _retain(self, size, category='curved-volume-scratch'):
        # One scratch-retention policy for both exact routes. The native twin
        # measures the same bit lengths itself and charges the same amount here,
        # then its own surcharge under NATIVE_RETAINED.
        if self.lease is None:
            self.stack.enter_context(self.resource.reserve(size, category=category))
        else:
            self.lease.add(size, category=category)


def _points(poly):
    return tuple(sorted({p for face in poly for p in face}))


def _box(cell):
    """Exact Cartesian topology under the caller's existing arithmetic lease.

    A reflected orthogonal basis reverses winding. Rotating each outward ring
    to its smallest world vertex reproduces _face's canonical ordered tuple.
    """
    points = tuple(tuple(o+sum(b*q for b, q in zip(row, point))
                         for o, row in zip(cell.origin_m, cell.basis))
                   for point in product(*zip(cell.lower_m, cell.upper_m)))
    reflected = O._dot(cell.basis[0], O._cross(cell.basis[1], cell.basis[2])) < 0
    faces = []
    for indices in _BOX_RINGS:
        if reflected:
            indices = indices[::-1]
        ring = tuple(points[i] for i in indices)
        start = min(range(4), key=ring.__getitem__)
        faces.append(ring[start:]+ring[:start])
    return tuple(faces)


def _plane_integer_rows(points, plane):
    """Exact plane values with positive common denominators, under V._work.

    Clear denominators once per plane and vertex. Classify using the integer
    numerator, then normalise Fractions only when a cut needs intersections.
    This is algebraically identical to dot(normal, point)-limit and retains
    exact constructions; no floating predicate or small-feature tolerance.
    """
    common = math.lcm(*(q.denominator for q in plane))
    coeff = tuple(q.numerator*(common//q.denominator) for q in plane)
    rows = {}
    for point in points:
        den = math.lcm(*(q.denominator for q in point))
        num = sum(coeff[i]*point[i].numerator*(den//point[i].denominator)
                  for i in range(3))-coeff[3]*den
        rows[point] = num, common*den
    return rows


def _clip(poly, plane, arena):
    """Exact convex-polyhedron clipping; only EXACT zero-volume faces vanish."""
    if not poly:
        return ()
    normal, limit = plane[:3], plane[3]
    if not any(normal):
        return poly if limit >= 0 else ()
    points = _points(poly)
    arena.work(16+8*len(points))
    values = (*(v for p in points for v in p), *plane)
    with V._work(values, arena.resource):
        rows = _plane_integer_rows(points, plane)
        if max(row[0] for row in rows.values()) <= 0:
            return poly
        if min(row[0] for row in rows.values()) >= 0:
            return ()
        # Positive row denominators let integer numerators decide every side.
        # Admit both directed edge keys and the longer-lived integer row payload
        # before allocating the cache. Only true straddles construct a ratio.
        row_bytes = 256*len(rows)+4*sum((n.bit_length()+d.bit_length()+7)//8
                                      for n, d in rows.values())
        cache_bytes = 1024+768*sum(map(len, poly))+row_bytes
        with arena.resource.reserve(cache_bytes, category='curved-clip-edge-cache'):
            intersections = {}
            try:
                faces, cap = [], set()
                for face in poly:
                    out = []
                    for a, b in zip(face, face[1:]+face[:1]):
                        na, da = rows[a]
                        nb, db = rows[b]
                        if na <= 0:
                            out.append(a)
                            if na == 0:
                                cap.add(a)
                        if (na < 0 < nb) or (nb < 0 < na):
                            point = intersections.get((a, b))
                            if point is None:
                                numerator = na*db
                                t = Q(numerator, numerator-nb*da)
                                point = tuple(a[j]+t*(b[j]-a[j]) for j in range(3))
                                intersections[a, b] = point
                                intersections[b, a] = point
                            out.append(point)
                            cap.add(point)
                    if len(out) >= 3:
                        # Distinct adjacent vertices and non-collinearity are
                        # exact predicates, never a small-face tolerance.
                        unique = tuple(p for i, p in enumerate(out) if p != out[i-1])
                        if len(unique) >= 3 and any(any(O._cross(O._minus(unique[i], unique[0]),
                                O._minus(unique[i+1], unique[0]))) for i in range(1, len(unique)-1)):
                            faces.append(unique)
                cap = tuple(sorted(cap))
                if len(cap) >= 3:
                    ring = O._face(cap, tuple(range(len(cap))), normal)
                    if ring is not None:
                        faces.append(tuple(cap[i] for i in ring))
                result = tuple(faces)
                retained = _points(result)
                arena.keep(tuple(v for p in retained for v in p), sum(map(len, result)))
                return result
            finally:
                intersections.clear()


def _volume(poly, arena, *, _consume=None):
    if not poly:
        return Q(0) if _consume is None else _consume(Q(0))
    points = _points(poly)
    arena.work(8+4*sum(map(len, poly)))
    with V._work(tuple(v for p in points for v in p), arena.resource):
        # A vertex is in the convex body. Its face pyramids have nonnegative
        # outward determinants; no global cancellation or absolute-value repair.
        origin, six_volume = points[0], Q(0)
        # Relative integer vectors coexist; origin subtraction can replicate
        # its width into every row. Admit four payload copies plus row/dict
        # overhead before construction, using a denominator per vertex.
        bits = sum(V._bits(q) for p in points for q in p)+len(points)*sum(V._bits(q) for q in origin)
        storage = 1024+512*len(points)+4*((4*bits+8*len(points)+7)//8)
        with arena.resource.reserve(storage, category='curved-volume-integer-vectors'):
            vectors = {}
            for point in points:
                if point == origin:
                    continue
                delta = O._minus(point, origin)
                den = math.lcm(*(q.denominator for q in delta))
                vectors[point] = tuple(q.numerator*(den//q.denominator) for q in delta), den
            for face in poly:
                if face[0] == origin:
                    continue
                a, da = vectors[face[0]]
                for i in range(1, len(face)-1):
                    if face[i] == origin or face[i+1] == origin:
                        continue
                    b, db = vectors[face[i]]
                    c, dc = vectors[face[i+1]]
                    determinant = (a[0]*(b[1]*c[2]-b[2]*c[1])
                                   +a[1]*(b[2]*c[0]-b[0]*c[2])
                                   +a[2]*(b[0]*c[1]-b[1]*c[0]))
                    if determinant < 0:
                        raise V.VolumeError('invalid outward convex-face orientation')
                    if determinant:
                        six_volume += Q(determinant, da*db*dc)
            result = six_volume/6
            return result if _consume is None else _consume(result)


# The resident-kernel interface. A complete operation asks _resident() once for
# the module whose _box/_plane/_clip/_volume/... it uses from its first clip to
# its last determinant. On this reference route a plane and a value are already
# what the kernels use, so the conversions are identities.
def _plane(plane):
    return plane


def _negated(plane):
    return tuple(-v for v in plane)


def _exact(value):
    return value


def _bits(value):
    return V._bits(value)


def _own(poly, arena):
    """Reference polyhedra carry no native surcharge to hand to an owner."""


def _retained_extra(polys):
    return 0


def _total(values):
    return sum(values, Q(0))


def _arithmetic(values, resource):
    return V._work(values, resource)


def _owned_box(cell, arena):
    """Admit construction and transfer retained ownership before release."""
    with _arithmetic(cell._geometry(), arena.resource):
        poly = _box(cell)
        values = tuple(v for point in _points(poly) for v in point)
        size = 1024+128*len(values)+128*sum(map(len, poly))+4*sum((V._bits(v)+7)//8 for v in values)
        with ExitStack() as pending:
            pending.enter_context(arena.resource.reserve(size, category='curved-volume-scratch'))
            _own(poly, arena)
            arena.stack.enter_context(pending.pop_all())
        return poly


def _scalar_memory(value):
    return value, 128+4*((V._bits(value)+7)//8), 0


class _ScalarSum:
    """Only the current exact total stays charged between admitted additions."""
    def __init__(self, kernel, arena):
        self.kernel, self.resource = kernel, arena.resource
        self.value, self.live = kernel._total(()), ExitStack()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.value = None
        return self.live.__exit__(*args)

    def add(self, value):
        K = self.kernel
        with K._arithmetic((self.value, value), self.resource):
            result, size, extra = K._scalar_memory(self.value+value)
            with ExitStack() as pending:
                pending.enter_context(self.resource.reserve(size, category='curved-volume-running-total'))
                if extra:
                    pending.enter_context(self.resource.reserve(extra, category=NATIVE_RETAINED))
                previous, self.live = self.live, pending.pop_all()
            self.value = result
            previous.close()

    def exact(self):
        with self.kernel._arithmetic((self.value,), self.resource):
            return self.kernel._exact(self.value)


def _total_volumes(polys, arena):
    with _ScalarSum(_python, arena) as total:
        for poly in polys:
            if _volume is _reference[2]:
                _volume(poly, arena, _consume=total.add)
            else:
                # Replaced reference kernels retain their two-argument
                # instrumentation contract and already return plain Fractions.
                total.add(_volume(poly, arena))
        return total.exact()


def _volume_exact(poly, arena):
    return _volume(poly, arena)


def _barycentre(poly):
    vertices = _points(poly)
    return tuple(sum(v[j] for v in vertices)/len(vertices) for j in range(3))


def _barycentre_admitted(poly, arena):
    vertices = _points(poly)
    with _arithmetic((*(v for point in vertices for v in point), len(vertices)), arena.resource):
        return _barycentre(poly)


def _all_beyond(plane, points):
    return all(O._dot(plane[:3], x) >= plane[3] for x in points)


def _all_within(plane, points):
    return all(O._dot(plane[:3], x) <= plane[3] for x in points)


def _outside_holes(poly, holes, arena, kernel=None):
    """Disjoint convex partition of poly minus the UNION of actual boxes.

    A box complement is split at its first violated halfspace. Thus parts do
    not overlap in positive volume, even when the input holes overlap. No
    inclusion-exclusion explosion or hull over gaps is used.
    """
    K = _python if kernel is None else kernel
    parts = [poly]
    for hole_planes in holes:
        remaining = []
        for part in parts:
            inside = part
            for plane in hole_planes:
                outside = K._clip(inside, K._negated(plane), arena)
                if outside:
                    remaining.append(outside)
                inside = K._clip(inside, plane, arena)
                if not inside:
                    break
        parts = remaining
        if not parts:
            break
    return parts


def _bound_leaf(layer, cone_planes, cell, holes, resource):
    K = _resident()
    with _Arena(resource) as arena:
        values = (*layer._geometry(), *cell._geometry(), *(q for p in cone_planes for q in p),
                  *(q for group in holes for p in group for q in p))
        with V._work(values, resource):
            radius, top, bottom = layer._geometry()
            inner2, outer2 = (radius-bottom)**2, (radius-top)**2
            minimum, maximum = cell._radial_bounds()
            if minimum >= outer2 or maximum <= inner2:
                return Q(0), Q(0), arena.work_units
            poly = K._box(cell)
            K._own(poly, arena)
            for plane in cone_planes:
                poly = K._clip(poly, K._plane(plane), arena)
                if not poly:
                    return Q(0), Q(0), arena.work_units
            candidates = []
            points = K._points(poly)
            for planes in holes:
                arena.work(12*len(points)*len(planes))
                planes = tuple(K._plane(p) for p in planes)
                # Exact halfspace broadphase. Equality is measure-zero contact.
                if any(K._all_beyond(p, points) for p in planes):
                    continue
                if all(K._all_within(p, points) for p in planes):
                    return Q(0), Q(0), arena.work_units
                candidates.append(planes)
            parts = _outside_holes(poly, candidates, arena, K)
            if minimum >= inner2 and maximum <= outer2:
                value = K._total_volumes(parts, arena)
                return value, value, arena.work_units
            local = tuple((a+b)/2 for a, b in zip(cell.lower_m, cell.upper_m))
            centre = tuple(cell.origin_m[i]+sum(cell.basis[i][j]*local[j] for j in range(3)) for i in range(3))
            squared = sum(c*c for c in centre)
            residual = sum(((b-a)/2)**2 for a, b in zip(cell.lower_m, cell.upper_m))
            gradient = tuple(2*c for c in centre)
            # L=gradient.x-|centre|² and 0<=|x-centre|²<=residual.
            inward = (*gradient, outer2+squared-residual)
            inner_planes = (inward, (*(-v for v in gradient), -inner2-squared))
            outer_planes = ((*gradient, outer2+squared),
                            (*(-v for v in gradient), residual-inner2-squared))
            bounds = []
            for planes in (inner_planes, outer_planes):
                planes = tuple(K._plane(p) for p in planes)
                def clipped_parts():
                    for part in parts:
                        for plane in planes:
                            part = K._clip(part, plane, arena)
                            if not part:
                                break
                        yield part
                bounds.append(K._total_volumes(clipped_parts(), arena))
            if not 0 <= bounds[0] <= bounds[1] <= cell.volume_m3:
                raise V.VolumeError('curved integration enclosure violates exact volume ordering')
            return *bounds, arena.work_units


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class VolumeEnclosure:
    layer_id: str
    cone_id: str
    cell_id: str
    hole_ids: tuple
    lower_m3: Q
    upper_m3: Q
    max_width_m3: Q
    leaves: int
    max_leaves: int
    predicate_units: int
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('VolumeEnclosure is issued by enclose_shell_cell()')

    @property
    def unresolved_volume_m3(self):
        return self.upper_m3-self.lower_m3

    @property
    def midpoint_m3(self):
        return (self.upper_m3+self.lower_m3)/2

    @property
    def meets_budget(self):
        return self.unresolved_volume_m3 <= self.max_width_m3

    def weighted_bounds(self, densities):
        """Bounds for constant extensive-per-volume fields; signed values work.

        Midpoint allocation has absolute amount error <=abs(q)*(upper-lower)/2.
        This is a geometric integration bound, not a bound on source provenance,
        transport reconstruction, physical modelling or time discretisation.
        """
        if type(densities) is not tuple or any(type(q) not in (int, Q) for q in densities):
            raise V.VolumeError('explicit exact int/Fraction scalar-density tuple required')
        with V._work((*densities, self.lower_m3, self.upper_m3), self._resource):
            return tuple((min(q*self.lower_m3, q*self.upper_m3),
                          max(q*self.lower_m3, q*self.upper_m3)) for q in densities)

    def record(self):
        with V._work((self.lower_m3, self.upper_m3, self.max_width_m3), self._resource):
            return dict(schema='atlas.curved-volume-enclosure.v1', method=METHOD,
                layer_id=self.layer_id, cone_id=self.cone_id, cell_id=self.cell_id,
                hole_ids=list(self.hole_ids), lower_m3=V._encoded(self.lower_m3),
                upper_m3=V._encoded(self.upper_m3), max_width_m3=V._encoded(self.max_width_m3),
                leaves=self.leaves, max_leaves=self.max_leaves, predicate_units=self.predicate_units,
                meets_budget=self.meets_budget,
                status='within explicit integration budget' if self.meets_budget else 'subdivision budget exhausted',
                scope='spatial geometric enclosure only; unresolved volume retained; no stock debit or time flux')

    @property
    def enclosure_id(self):
        return hashlib.sha256(json.dumps(self.record(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def enclose_shell_cell(layer, cone_vertices, cell, *, holes=(), max_width_m3, max_leaves, budget):
    """Certify cell intersect cone intersect radial shell minus oriented boxes.

    Caller error and subdivision budgets are mandatory. The latter is a work
    bound, not a scientific tolerance; reaching it returns an explicitly unmet
    enclosure. WorkBudget refusal remains atomic. Every nonzero uncertain leaf
    participates in the result. No partial volume is silently omitted.
    """
    if type(layer) is not V.RadialLayer or type(cell) is not V.CartesianCell:
        raise V.VolumeError('typed physical radial layer and Cartesian cell required')
    if type(holes) is not tuple or any(type(h) is not V.CartesianCell for h in holes):
        raise V.VolumeError('holes must be an explicit tuple of actual Cartesian cells')
    if type(max_width_m3) not in (int, Q) or max_width_m3 < 0:
        raise V.VolumeError('nonnegative exact volume-width budget required')
    if type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive finite integer subdivision budget required')
    resource = select_budget(budget)
    with _Arena(resource) as state:
        state.keep((Q(max_width_m3),), len(holes))
        cone = V.convex_cone_union((cone_vertices,), budget=resource)
        cone_planes = tuple(O._plane(tuple(-v for v in O._cross(a, b)), 0)
                            for a, b in zip(cone, cone[1:]+cone[:1]))
        by_id = {h.cell_id: h for h in holes}
        hole_ids = tuple(sorted(by_id))
        with V._work(tuple(q for key in hole_ids for q in by_id[key]._geometry()), resource):
            planes = tuple(tuple(O._box_planes(by_id[key])) for key in hole_ids)
        state.keep(tuple(v for group in planes for p in group for v in p), 6*len(planes))
        low, high, work = _bound_leaf(layer, cone_planes, cell, planes, resource)
        best_low, best_high = low, high
        sequence, leaves = 0, 1
        queue = [(low-high, sequence, cell, low, high)] if high > low else []
        while queue and best_high-best_low > max_width_m3 and leaves < max_leaves:
            _, _, parent, a, b = heapq.heappop(queue)
            axis = max(range(3), key=lambda j: parent.upper_m[j]-parent.lower_m[j])
            middle = (parent.lower_m[axis]+parent.upper_m[axis])/2
            children = []
            for right in (False, True):
                lower, upper = list(parent.lower_m), list(parent.upper_m)
                (lower if right else upper)[axis] = middle
                child = V.CartesianCell(tuple(lower), tuple(upper), parent.origin_m, parent.basis, budget=resource)
                lo, hi, effort = _bound_leaf(layer, cone_planes, child, planes, resource)
                work += effort
                sequence += 1
                state.work(effort)
                state.keep((*child._geometry(), lo, hi), 1)
                if hi > lo:
                    heapq.heappush(queue, (lo-hi, sequence, child, lo, hi))
                children.append((lo, hi))
            # Maintain the current disjoint leaf sums. Their enclosures are
            # valid independently; no monotonicity of tangent planes is assumed.
            with V._work((low, high, a, b, *(v for p in children for v in p)), resource):
                low += sum(p[0] for p in children)-a
                high += sum(p[1] for p in children)-b
                best_low, best_high = max(best_low, low), min(best_high, high)
            leaves += 1
        result = object.__new__(VolumeEnclosure)
        cone_id = hashlib.sha256(json.dumps([[V._encoded(v) for v in p] for p in cone],
                                             separators=(',', ':')).encode()).hexdigest()
        values = dict(layer_id=layer.layer_id, cone_id=cone_id, cell_id=cell.cell_id, hole_ids=hole_ids,
            lower_m3=best_low, upper_m3=best_high, max_width_m3=Q(max_width_m3), leaves=leaves,
            max_leaves=max_leaves, predicate_units=work, _resource=resource)
        for name, value in values.items():
            object.__setattr__(result, name, value)
        lease = resource.reserve(8192+256*len(hole_ids)+4*sum((V._bits(q)+7)//8 for q in
            (best_low, best_high, Q(max_width_m3))), category='curved-volume-retained')
        lease.__enter__()
        try:
            weakref.finalize(result, lease.__exit__, None, None, None)
        except BaseException:
            lease.__exit__(None, None, None)
            raise
        return result


_python = sys.modules[__name__]
_gmp = None
if X.BACKEND == 'gmpy2':
    from . import integration_exact_gmp as _gmp
# The reference kernel as loaded. A diagnostic that wraps or replaces any of
# these expects every complete operation to pass through its replacement.
_reference = (_box, _clip, _volume, _points, _plane_integer_rows, _Arena.keep,
              _Arena._retain, Q, V._work, O._face, O._cross, O._minus)


def _resident():
    """The exact kernel for ONE complete operation, fixed at its entry.

    Returns this module (Fraction/int) or its GMP-resident twin. The choice is
    never changed inside an operation and a native error is never retried on
    the other route: both compute the same rationals and the same work units
    and make the same reference reservations; the twin additionally reserves
    its native surcharge (NATIVE_RETAINED), so it can refuse where the
    reference admits, never the reverse. The process backend is
    exact_arithmetic.BACKEND. The reference route is also kept whenever a
    reference kernel function has been wrapped or replaced, so instrumentation
    and substituted reference kernels still see every clip and volume. That
    test is object identity on this module, _Arena and the two helper
    modules; an override set on one arena instance is not seen.
    """
    if _gmp is None:
        return _python
    current = (_box, _clip, _volume, _points, _plane_integer_rows, getattr(_Arena, 'keep', None),
               getattr(_Arena, '_retain', None), Q, V._work, O._face, O._cross, O._minus)
    for now, loaded in zip(current, _reference, strict=True):
        if now is not loaded:
            return _python
    return _gmp
