"""Position-preserving I03 material patches, distinct from the sampling faces.

The immutable cells are convex spherical polygons in their owner's plate frame.
Their vertices are primitive integer homogeneous directions: intersection side
tests and new vertices are exact for the declared binary64 directions. No
positive-area fragment is discarded. Extensive patch stocks remain exact binary
fractions and are reconciled with the already-accounted rounding of each piece.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from decimal import Decimal, localcontext, ROUND_FLOOR, ROUND_CEILING
from fractions import Fraction
from functools import wraps
from types import MappingProxyType
import hashlib
import json
import math

import numpy as np

from ._validation import TectonicsError
from .resources import select_budget, MemoryLimitError

SCHEMA = 'atlas.i03-material-support.v1'
DENSITY_SCHEMA = 'atlas.i03-material-support.v2'
BUDGET_SCHEMA = 'atlas.i03-material-support.v3'
MAX_CELLS = 1 << 20
LEGACY_COORDINATE_BITS = 4096
_ARENA = ContextVar('i03_exact_geometry_arena', default=None)
_END = object()


class SupportError(TectonicsError):
    """Missing or unresolved material geometry; never permission to homogenise."""


class _GeometryArena:
    """One bounded operation, not a persistent global geometry cache.

    Generated cells remain charged until the operation ends, even if a local
    intermediate dies earlier. Exact equal cells share tuples. The input and
    output states remain caller-owned buffers, as in the existing step API.
    """
    def __init__(self, budget, stack):
        self.budget, self.stack, self.cells = budget, stack, {}

    def retain(self, cell):
        if not cell:
            return ()
        old = self.cells.get(cell)
        if old is not None:
            return old
        if len(self.cells) >= MAX_CELLS:
            raise SupportError('exact geometry operation exceeds the cell work limit; no cells are culled')
        # Tuple/dict bookkeeping, integer objects and their limbs, with room
        # for a second canonical tuple. Decimal/hex payload copies are covered
        # separately by Support.workspace_bytes when issuing a material.
        count = 256 + sum(128 + sum(64 + (abs(v).bit_length()+7)//8 for v in p) for p in cell)
        self.stack.enter_context(self.budget.reserve(count, category='i03-exact-cells'))
        self.cells[cell] = cell
        return cell


@contextmanager
def geometry_workspace(budget=None, *, support=None):
    """Join the current operation or open a caller-budget-bounded exact arena.

    All reservations, including partially completed work, leave in finally.
    No coordinate is rounded to fit the budget. This accounts workspace, not RSS.
    """
    current = _ARENA.get()
    if current is not None:
        if budget is not None and select_budget(budget) is not current.budget:
            raise SupportError('nested material geometry must use the current caller budget')
        yield current
        return
    with ExitStack() as stack:
        arena = _GeometryArena(select_budget(budget), stack)
        if support is not None:
            stack.enter_context(arena.budget.reserve(support.workspace_bytes(), category='i03-exact-input'))
            arena.cells.update((c, c) for p in support.patches for c in p.cells)
        token = _ARENA.set(arena)
        try:
            yield arena
        finally:
            _ARENA.reset(token)


def _integer_extent(values):
    count, bits = 0, 1
    pending = [iter(values)]
    while pending:
        value = next(pending[-1], _END)
        if value is _END:
            pending.pop()
            continue
        if type(value) is int:
            count += 1
            bits = max(bits, abs(value).bit_length())
        elif isinstance(value, Fraction):
            pending.append(iter((value.numerator, value.denominator)))
        elif isinstance(value, (tuple, list)):
            pending.append(iter(value))
        elif isinstance(value, Patch):
            pending.append(iter(value.cells))
    return count, bits


def _bounded_geometry(function=None, *, scratch_inputs=None):
    if function is None:
        return lambda selected: _bounded_geometry(selected, scratch_inputs=scratch_inputs)
    @wraps(function)
    def bounded(*args, **kwargs):
        with geometry_workspace() as arena:
            count, bits = _integer_extent((args, tuple(kwargs.values())))
            # Each predicate/clip/map uses a fixed number of integer buffers.
            # 64 buffers per input integer, each with eight input bit-widths,
            # covers unreduced products (clip <= 3B+3, map <= 3B+4,
            # determinant <= 3B+2, squared cross norm <= 4B+2), GCD/division
            # scratch, Decimal conversion and canonicalisation. Nested calls
            # reserve their own actual larger width before further arithmetic.
            # Area and projective traversal operate on one triangle/point at
            # a time, not all cells simultaneously. Small result/list buffers
            # remain charged for the complete input count.
            live = count if scratch_inputs is None else min(count, scratch_inputs)
            scratch = 65536 + 128*count + 64*max(live, 3)*(32+bits+1)
            with arena.budget.reserve(scratch, category='i03-exact-arithmetic'):
                return function(*args, **kwargs)
    return bounded


def _coordinate(value):
    return str(value) if abs(value).bit_length() <= LEGACY_COORDINATE_BITS else hex(value)


def _tools():
    from . import integration_transfer as T
    return T


@_bounded_geometry
def _canonical(cell):
    T = _tools()
    points = list(dict.fromkeys(T._primitive(tuple(p)) for p in cell))
    while len(points) >= 3:
        k = next((i for i in range(len(points))
                  if T._dot(points[i-1], T._cross(points[i], points[(i+1) % len(points)])) == 0), None)
        if k is None:
            break
        points.pop(k)
    if len(points) < 3:
        return ()
    if T._dot(points[0], T._cross(points[1], points[2])) < 0:
        points.reverse()
    start = min(range(len(points)), key=points.__getitem__)
    return _ARENA.get().retain(tuple(points[start:]+points[:start]))


@_bounded_geometry
def _half(cell, normal):
    T = _tools()
    out = []
    for p, q in zip(cell, cell[1:]+cell[:1]):
        dp, dq = T._dot(normal, p), T._dot(normal, q)
        if dp >= 0:
            out.append(p)
        if dp*dq < 0:
            out.append(T._primitive(tuple((y*dp-x*dq)*T._sign(dp-dq) for x, y in zip(p, q))))
    return _canonical(out)


def intersect_cell(first, second):
    if first == second:
        return first
    T = _tools()
    cell = first
    for a, b in zip(second, second[1:]+second[:1]):
        cell = _half(cell, T._cross(a, b))
        if not cell:
            break
    return cell


def _subtract(first, second):
    """Disjoint convex pieces of first minus second, with exact side decisions."""
    T = _tools()
    inside, out = first, []
    for a, b in zip(second, second[1:]+second[:1]):
        normal = T._cross(a, b)
        outside = _half(inside, tuple(-v for v in normal))
        if outside:
            out.append(outside)
        inside = _half(inside, normal)
        if not inside:
            break
    return out


def cells_of_rings(rings):
    """Disjoint convex cells of a validated minor-arc polygon, holes subtracted."""
    T = _tools()
    centre = T._integers([T._sphere._mean_direction(np.asarray(rings[0]))])[0]
    cells = [_canonical(c) for c in T._exact_triangles(rings[0], centre)]
    for ring in rings[1:]:
        for hole in T._exact_triangles(ring, centre):
            cells = [part for cell in cells for part in _subtract(cell, _canonical(hole))]
    return tuple(sorted(set(c for c in cells if c)))


def intersection(first, second):
    if first == second:
        return first
    return tuple(sorted(set(c for a in first for b in second if (c := intersect_cell(a, b)))))


def difference(first, second):
    if first == second:
        return ()
    cells = list(first)
    for clip in second:
        cells = [part for cell in cells for part in _subtract(cell, clip)]
    return tuple(cells)


def disjoint_union(cells, *, cancel=None):
    """Exact union for one local measurement; never count an overlap twice."""
    out = []
    for cell in sorted(set(cells)):
        _tools()._check_cancel(cancel)
        overlapping = tuple(old for old in out if intersect_cell(cell, old))
        out.extend(difference((cell,), overlapping) if overlapping else (cell,))
        if len(out) > MAX_CELLS:
            raise SupportError('exact local material union exceeds the existing cell limit')
    return tuple(out)


@dataclass(frozen=True)
class ExactFootprint:
    """Explicit initial support with exact homogeneous vertices, without a float roundtrip."""
    cells: tuple


def split_face(network, face_id, normal):
    """Positive and negative exact half-plane clips of a declared face.

    The plane normal is a finite nonzero binary64 vector in the owning plate's
    local frame. New intersections retain integer homogeneous directions; no
    normalised midpoint is silently snapped onto an edge.
    """
    normal = np.asarray(normal, dtype=float)
    if normal.shape != (3,) or not np.isfinite(normal).all() or not np.any(normal):
        raise SupportError('a material cut requires a finite nonzero local plane normal')
    T = _tools()
    exact = T._integers([normal])[0]
    cells = cells_of_rings(T._Shapes(network).rings(network.face_ids.index(face_id)))
    return tuple(ExactFootprint(tuple(part for cell in cells if (part := _half(cell, n))))
                 for n in (exact, tuple(-v for v in exact)))


@_bounded_geometry(scratch_inputs=9)
def area_sr(cells):
    T = _tools()
    return math.fsum(T._exact_triangle_sr(c[0], c[i], c[i+1])
                     for c in cells for i in range(1, len(c)-1))


@_bounded_geometry(scratch_inputs=9)
def area_interval_sr(cells, *, cancel=None):
    """Enclose the area of the exact rays, not uncertain historical positions.

    Integer products are exact. Directed 80-digit Decimal arithmetic brackets
    the triangle formula's square roots and denominator. Float argument
    conversion is bracketed too; atan2 uses the existing C7 one-ulp platform
    premise. Summation of the returned binary bounds is exact.
    """
    T = _tools()
    lower = upper_bound = Fraction(0)

    def float_bounds(value):
        rounded = float(value)
        exact = Fraction(value)
        q = Fraction(rounded)
        return (math.nextafter(rounded, -math.inf) if q > exact else rounded,
                math.nextafter(rounded, math.inf) if q < exact else rounded)

    with localcontext() as context:
        context.prec = 80
        for cell in cells:
            T._check_cancel(cancel)
            for i in range(1, len(cell)-1):
                a, b, c = cell[0], cell[i], cell[i+1]
                numerator = T._dot(a, T._cross(b, c))
                if numerator < 0:
                    raise SupportError('area interval requires positively oriented convex cells')
                if not numerator:
                    continue
                roots = []
                for p in (a, b, c):
                    root = Decimal(T._dot(p, p)).sqrt()
                    roots.append((root.next_minus(), root.next_plus()))
                products = (T._dot(b, c), T._dot(c, a), T._dot(a, b))
                denominator = []
                for side, rounding in ((0, ROUND_FLOOR), (1, ROUND_CEILING)):
                    context.rounding = rounding
                    value = roots[0][side]*roots[1][side]*roots[2][side]
                    for dot, root in zip(products, roots):
                        value += Decimal(dot)*root[side if dot >= 0 else 1-side]
                    denominator.append(value)
                scale = max(Decimal(numerator), *(abs(v) for v in denominator))
                context.rounding = ROUND_FLOOR
                nlo = float_bounds(Decimal(numerator)/scale)[0]
                dlo = float_bounds(denominator[0]/scale)[0]
                context.rounding = ROUND_CEILING
                nhi = float_bounds(Decimal(numerator)/scale)[1]
                dhi = float_bounds(denominator[1]/scale)[1]
                angles = [math.atan2(n, d) for n in (nlo, nhi) for d in (dlo, dhi)]
                # One ulp, rather than just one neighbouring float: at a power
                # of two the lower neighbouring spacing can be half an ulp.
                lower += 2*max(Fraction(0), min(Fraction(v)-Fraction(math.ulp(v)) for v in angles))
                upper_bound += 2*max(Fraction(v)+Fraction(math.ulp(v)) for v in angles)
    return lower, upper_bound


@_bounded_geometry(scratch_inputs=6)
def perimeter_rad(cell):
    """Minor-arc perimeter without collapsing nearby homogeneous vertices."""
    T = _tools()
    angles = []
    with localcontext() as context:
        context.prec = 80
        for p, q in zip(cell, cell[1:]+cell[:1]):
            cross = T._cross(p, q)
            sine, cosine = Decimal(T._dot(cross, cross)).sqrt(), Decimal(T._dot(p, q))
            scale = max(sine, abs(cosine))
            angles.append(math.atan2(float(sine/scale), float(cosine/scale)))
    return math.fsum(angles)


@_bounded_geometry(scratch_inputs=3)
def directions(cell):
    # Divide integers before conversion, so large exact intersections cannot overflow.
    out = np.asarray([[float(Fraction(v, max(map(abs, p)))) for v in p] for p in cell])
    return out/np.linalg.norm(out, axis=1)[:, None]


@_bounded_geometry
def _rational_ray(point):
    denominator = math.lcm(*(v.denominator for v in point))
    ray = _tools()._primitive(tuple(v.numerator*(denominator//v.denominator) for v in point))
    return ray


def turned_ray(point, turns):
    """Exact rotation of a binary64 ray; no subtraction of placed endpoints."""
    value = tuple(Fraction(float(v)) for v in point)
    for turn in turns:
        w, x, y, z = (Fraction(v) for v in turn.quaternion)
        norm = w*w+x*x+y*y+z*z
        matrix = ((w*w+x*x-y*y-z*z, 2*(x*y-w*z), 2*(x*z+w*y)),
                  (2*(x*y+w*z), w*w-x*x+y*y-z*z, 2*(y*z-w*x)),
                  (2*(x*z-w*y), 2*(y*z+w*x), w*w-x*x-y*y+z*z))
        value = tuple(sum((entry*v for entry, v in zip(row, value)), Fraction(0))/norm for row in matrix)
    return _rational_ray(value)


def _near_unit(point):
    # Scaling does not change this exact ray. Dyadic reciprocal scales avoid
    # introducing unrelated large denominators into every triangle cofactor.
    # The subsequent exact displacement proof includes this scale's rounding.
    values = tuple(Fraction(v, 1 << max(abs(v).bit_length() for v in point)) for v in point)
    squared = sum((v*v for v in values), Fraction(0))
    reciprocal = Fraction(1/math.sqrt(float(squared)))
    return tuple(v*reciprocal for v in values)


@_bounded_geometry
def _placement_map(source, target):
    """Positive-coefficient re-expression under the unchanged four-epsilon bound.

    Source rays are exact, target vectors the stored endpoint directions. The
    bound is evaluated on rational near-unit vectors, so no float conversion of
    a small angular displacement occurs in the proof.
    """
    from . import integration_events as E
    T = _tools()
    centre = T._integers([T._sphere._mean_direction(np.asarray(target))])[0]
    triangles = tuple(_canonical(c) for c in T._integer_triangles(source, centre))
    indices = {p: i for i, p in enumerate(source)}
    old = tuple(_near_unit(p) for p in source)
    new = tuple(tuple(Fraction(float(v)) for v in p) for p in target)
    prepared = []
    for triangle in triangles:
        selected = [indices[p] for p in triangle]
        a, b = tuple(old[i] for i in selected), tuple(new[i] for i in selected)
        normal = tuple(Fraction(v) for v in centre)
        c = min(T._dot(normal, p) for p in a)
        d2 = max(sum(((x-y)**2 for x, y in zip(p, q)), Fraction(0)) for p, q in zip(a, b))
        if c <= 0:
            raise SupportError('precise motion has no conditioned re-expression hemisphere')
        eta2 = d2*T._dot(normal, normal)/(c*c)
        eta = math.sqrt(float(eta2))
        while Fraction(eta)**2 < eta2:
            eta = math.nextafter(eta, math.inf)
        ratio = Fraction(eta)
        if ratio >= 1 or ratio/(1-ratio) > Fraction(E.REEXPRESSION_ROUNDING):
            raise SupportError('precise motion re-expression exceeds the existing four-epsilon angular bound')
        # Common denominators within each source/target triangle preserve the
        # near-unit lengths used in that proof, not independent primitive scales.
        scale_a = math.lcm(*(v.denominator for p in a for v in p))
        scale_b = math.lcm(*(v.denominator for p in b for v in p))
        ia = tuple(tuple(int(v*scale_a) for v in p) for p in a)
        ib = tuple(tuple(int(v*scale_b) for v in p) for p in b)
        cofactors = (T._cross(ia[1], ia[2]), T._cross(ia[2], ia[0]), T._cross(ia[0], ia[1]))
        prepared.append((triangle, ib, cofactors, T._sign(T._dot(ia[0], cofactors[0]))))
    mapped = tuple(_canonical(tuple(T._primitive(p) for p in row[1])) for row in prepared)
    own = cells_of_rings((np.asarray(target),))
    if difference(mapped, own) or difference(own, mapped):
        raise SupportError('precise motion needs a matching endpoint triangulation')
    return triangles, tuple(prepared)


def motion_geometry(network, endpoint, geometry, *, cancel=None):
    """Exact rigid-trench cuts plus bounded re-expression into the endpoint mesh.

    A non-rigid junction remains on its existing explicitly constructed route.
    No higher-order trajectory is inferred from its endpoint.
    """
    if not geometry.precise_trenches:
        return None
    T = _tools()
    old_indices = {v: i for i, v in enumerate(network.vertex_ids)}
    new_indices = {v: i for i, v in enumerate(endpoint.vertex_ids)}
    plates = {p: i for i, p in enumerate(network.plate_ids)}
    new_plates = {p: i for i, p in enumerate(endpoint.plate_ids)}
    replacements, sweep_cells = {}, {}
    boundaries = {b.boundary_id: b for b in network.boundaries}
    for boundary_id, plate, entries in geometry.precise_trenches:
        T._check_cancel(cancel)
        points = dict(entries)
        replacements.setdefault(plate, {}).update(points)
        boundary = boundaries[boundary_id]
        chain = boundary.vertex_ids
        steps = list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])
        for a, b in steps:
            local = network._local[plates[plate]]
            p, q = (T._primitive(v) for v in T._integers([local[old_indices[a]], local[old_indices[b]]]))
            ring = (p, q, points[b], points[a]) if boundary.subducting_side == 'left' else (
                    q, p, points[a], points[b])
            cell = _canonical(ring)
            if cell:
                sweep_cells.setdefault((boundary_id, plate), []).append(cell)
    receivers = {}
    for i, face in enumerate(endpoint.faces):
        T._check_cancel(cancel)
        points = replacements.get(face.plate_id, {})
        if not any(name in points for name in face.vertex_ids):
            continue
        target = endpoint._local[new_plates[face.plate_id]][[new_indices[v] for v in face.vertex_ids]]
        source = tuple(points.get(name, T._primitive(p))
                       for name, p in zip(face.vertex_ids, T._integers(target)))
        receivers[i] = _placement_map(source, target)
    return receivers, {key: tuple(value) for key, value in sweep_cells.items()}


def _payload(face, cohort, cells, stock, area_allowance):
    return [face, cohort, [[[_coordinate(v) for v in p] for p in cell] for cell in cells],
            [[str(v.numerator), str(v.denominator)] for v in stock], area_allowance]


@dataclass(frozen=True, slots=True)
class Patch:
    face_id: str
    cohort_id: str
    cells: tuple
    stock: tuple
    area_allowance_m2: float = 0.
    declared_density: tuple | None = None
    _position_id: str = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if (type(self.cells) is not tuple or type(self.stock) is not tuple or
                any(type(cell) is not tuple or any(type(p) is not tuple for p in cell) for cell in self.cells)):
            raise SupportError('material patch geometry and stocks must be immutable tuples')
        if self.declared_density is not None and (
                type(self.declared_density) is not tuple or len(self.declared_density) != len(self.stock) or
                any(type(v) is not Fraction for v in self.declared_density) or self.declared_density[0] != 1):
            raise SupportError('a declared areal law is an exact coefficient tuple in stock-column order')
        # Position identity, independent of extensive bookkeeping rounding.
        with geometry_workspace() as arena:
            count, bits = _integer_extent(self.cells)
            with arena.budget.reserve(65536+count*(128+8*bits), category='i03-exact-encoding'):
                position = [self.face_id, self.cohort_id,
                            [[[_coordinate(v) for v in p] for p in cell] for cell in self.cells]]
                object.__setattr__(self, '_position_id',
                                   hashlib.sha256(json.dumps(position, separators=(',', ':')).encode()).hexdigest())

    @property
    def patch_id(self):
        return self._position_id

    def record(self):
        row = _payload(self.face_id, self.cohort_id, self.cells, self.stock, self.area_allowance_m2)
        if self.declared_density is not None:
            row.append([[str(v.numerator), str(v.denominator)] for v in self.declared_density])
        return row


def upper(value):
    rounded = float(value)
    return math.nextafter(rounded, math.inf) if Fraction(rounded) < value else rounded


def whole_face_allowance(network, index):
    """Only the pre-existing whole-face C7 measurement bound, in its approved range.

    Exact polygon evaluation adds its existing one-ulp atan premise and finite
    sum/product rounding, dominated by relative closure on non-thin faces.
    """
    T = _tools()
    rings = T._Shapes(network).rings(index)
    measured = float(network.face_area_m2[index])
    bound = T._sphere._measure_bound(rings)
    if bound is None:
        return 0.
    ceiling = T._c7_range_limit(rings, measured)
    return min(ceiling, bound*network.sphere.radius_m**2+4*math.ulp(measured))


def piece_of(patch, phases):
    """Detached I03 Piece allocation for existing column constitutive adapters."""
    from .integration_sphere import Piece
    k = len(phases)
    return Piece(patch.face_id, patch.cohort_id, float(patch.stock[0]),
                 tuple(float(v) for v in patch.stock[1:1+k]),
                 tuple(float(v) for v in patch.stock[1+k:1+2*k]),
                 None if len(patch.stock) == 1+2*k else float(patch.stock[-1]))


@dataclass(frozen=True, slots=True)
class Support:
    patches: tuple
    _pieces: object = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if type(self.patches) is not tuple or any(type(p) is not Patch for p in self.patches):
            raise SupportError('material support must be an immutable tuple of patches')
        grouped = {}
        for patch in self.patches:
            grouped.setdefault((patch.face_id, patch.cohort_id), []).append(patch)
        object.__setattr__(self, '_pieces', MappingProxyType({key: tuple(patches) for key, patches in grouped.items()}))

    def patches_of_piece(self, face_id, cohort_id):
        return self._pieces.get((face_id, cohort_id), ())

    def record(self):
        bits = max((abs(v).bit_length() for p in self.patches for c in p.cells for point in c for v in point), default=0)
        result = dict(schema=DENSITY_SCHEMA if any(p.declared_density is not None for p in self.patches) else SCHEMA,
                      patches=[p.record() for p in self.patches])
        if bits > LEGACY_COORDINATE_BITS:
            result.update(schema=BUDGET_SCHEMA, coordinate_bits=bits, coordinate_encoding='decimal-or-hex-v1')
        return result

    def workspace_bytes(self):
        """Conservative payload/validation allowance, not a measured peak claim.

        Eight bytes per integer bit covers Python integers, decimal JSON strings
        and canonical copies; polygon/list overhead is charged separately.
        """
        bits = sum(abs(v).bit_length() for p in self.patches for c in p.cells for point in c for v in point)
        bits += sum(v.numerator.bit_length()+v.denominator.bit_length() for p in self.patches for v in p.stock)
        bits += sum(v.numerator.bit_length()+v.denominator.bit_length() for p in self.patches
                    if p.declared_density is not None for v in p.declared_density)
        return 65536+8*bits+2048*len(self.patches)+512*sum(len(p.cells) for p in self.patches)

    @property
    def support_id(self):
        return hashlib.sha256(json.dumps(self.record(), separators=(',', ':')).encode()).hexdigest()


def required(material):
    support = material.support
    if support is None:
        raise SupportError('material positions are unknown in this saved representation; exact continuation needs '
                           'an explicit supported initial declaration, never inferred mixed-cell footprints')
    return support


def declared(network, face, cohort, stock, cohorts, footprints=None, *, areal_density=None):
    """Fresh single-piece faces imply their full face; mixed faces require explicit local-frame rings.

    footprints maps (face_id, cohort_id) to a sequence of polygons, each polygon a
    tuple of rings in that face's plate reference frame. These are declarations,
    not a reconstruction of a previously saved mixture.
    """
    T = _tools()
    shapes = T._Shapes(network)
    counts = {int(f): int(np.count_nonzero(face == f)) for f in face}
    supplied = {} if footprints is None else dict(footprints)
    explicit_faces = set()
    patches = []
    for f, c, values in zip(face, cohort, stock):
        key = network.face_ids[int(f)], cohorts[int(c)].cohort_id
        if key in supplied:
            declared_ = supplied.pop(key)
            cells = (declared_.cells if type(declared_) is ExactFootprint else
                     tuple(cell for rings in declared_ for cell in cells_of_rings(rings)))
            explicit_faces.add(key[0])
        elif counts[int(f)] == 1:
            cells = cells_of_rings(shapes.rings(int(f)))
        else:
            raise SupportError('mixed declaration %r needs explicit material footprints' % (key,))
        allowance = 0.
        if counts[int(f)] == 1:
            measured = float(network.face_area_m2[int(f)])
            exact_measure = area_sr(cells)*network.sphere.radius_m**2
            # _material still enforces the original authored occupancy gate.
            # Carry the two explicit discrepancies for this same whole polygon,
            # never a new allowance on arbitrary clipped geometry.
            declared_difference = abs(Fraction(float(values[0]))-Fraction(measured))
            evaluation_difference = abs(Fraction(measured)-Fraction(exact_measure))
            allowance = upper(declared_difference+max(Fraction(whole_face_allowance(network, int(f))),
                                                       evaluation_difference))
        patches.append(Patch(*key, cells, tuple(Fraction(float(v)) for v in values), allowance, areal_density))
    if supplied:
        raise SupportError('a footprint names no declared piece')
    for face_id in explicit_faces:
        own = cells_of_rings(shapes.rings(network.face_ids.index(face_id)))
        declared_cells = tuple(cell for p in patches if p.face_id == face_id for cell in p.cells)
        if difference(declared_cells, own) or difference(own, declared_cells):
            raise SupportError('explicit footprints must partition the exact declared face; rounded off-edge '
                               'cuts require split_face and ExactFootprint, never snapping')
    return Support(tuple(patches))


def checked(network, face, cohort, stock, cohorts, support, *, signed=False):
    """Exact stock joins and existing relative geometric closure; no new tolerance."""
    if type(support) is not Support or any(type(p) is not Patch for p in support.patches):
        raise SupportError('typed material support is required')
    T = _tools()
    keys = {(network.face_ids[int(f)], cohorts[int(c)].cohort_id): tuple(Fraction(float(v)) for v in row)
            for f, c, row in zip(face, cohort, stock)}
    found = {}
    radius2 = network.sphere.radius_m**2
    shapes = T._Shapes(network)
    cells_by_face = {}
    if sum(len(p.cells) for p in support.patches) > MAX_CELLS:
        raise SupportError('material support exceeds the explicit cell resource limit; no cells are culled')
    for patch in support.patches:
        key = patch.face_id, patch.cohort_id
        if key not in keys or not patch.cells or len(patch.stock) != len(keys[key]):
            raise SupportError('material support names a missing piece, empty geometry or incompatible stock')
        if any(type(v) is not Fraction for v in patch.stock) or patch.stock[0] <= 0:
            raise SupportError('patch amounts are exact fractions with positive area')
        if any(v < 0 for v in patch.stock[:-1] if signed) or (not signed and any(v < 0 for v in patch.stock)):
            raise SupportError('patch area, mass and volume are nonnegative')
        for value in patch.stock:
            T._sphere._account(value, 'patch stock')
        if patch.declared_density is not None:
            for k, value in enumerate(patch.declared_density):
                T._sphere._account(value, 'declared patch density')
                if value < 0 and (not signed or k < len(patch.stock)-1):
                    raise SupportError('declared area, mass and volume densities are nonnegative')
        if not math.isfinite(patch.area_allowance_m2) or patch.area_allowance_m2 < 0:
            raise SupportError('a patch geometry allowance must be finite and nonnegative')
        for cell in patch.cells:
            if any(type(v) is not int for p in cell for v in p):
                raise SupportError('material geometry requires exact integer coordinates')
            if _canonical(cell) != cell:
                raise SupportError('a material cell is not canonical')
            if any(T._dot(T._cross(a, b), p) < 0 for a, b in zip(cell, cell[1:]+cell[:1]) for p in cell):
                raise SupportError('a material cell is not convex')
        for i, cell in enumerate(patch.cells):
            if any(intersect_cell(cell, other) for other in patch.cells[i+1:]):
                raise SupportError('cells within a material patch overlap')
        measured = area_sr(patch.cells)*radius2
        if abs(measured-float(patch.stock[0])) > max(
                T.RELATIVE_TOLERANCE*max(measured, float(patch.stock[0])), patch.area_allowance_m2):
            raise SupportError('patch area and its retained geometry do not close within the existing tolerance')
        if patch.face_id not in cells_by_face:
            cells_by_face[patch.face_id] = cells_of_rings(shapes.rings(network.face_ids.index(patch.face_id)))
        own = cells_by_face[patch.face_id]
        held = measured if patch.cells == own else area_sr(intersection(patch.cells, own))*radius2
        if abs(held-measured) > T.RELATIVE_TOLERANCE*measured:
            raise SupportError('a material patch leaves its sampling face')
        total = found.setdefault(key, [Fraction(0)]*len(patch.stock))
        for k, value in enumerate(patch.stock):
            total[k] += value
    if {k: tuple(v) for k, v in found.items()} != keys:
        raise SupportError('exact patch stocks do not reproduce the material pieces')
    # Distinct cohorts may share an edge, never positive area. Same-cohort patches
    # also retain distinct amounts and must not double-own material.
    by_face = {}
    for patch in support.patches:
        by_face.setdefault(patch.face_id, []).append(patch)
    for patches in by_face.values():
        for i, a in enumerate(patches):
            for b in patches[i+1:]:
                if intersection(a.cells, b.cells):
                    raise SupportError('two material patches overlap with positive area')
    return support


def restore(record, *, budget=None):
    """Charge encoded input before integer conversion; never infer geometry."""
    # Four bits per hexadecimal character, less for decimal, with the existing
    # eight-bytes-per-bit payload allowance. Scan lengths before int() or copies.
    pending, encoded, cells = [iter((record,))], 65536, 0
    current = _ARENA.get()
    selected = current.budget if current is not None and budget is None else select_budget(budget)
    while pending:
        item = next(pending[-1], _END)
        if item is _END:
            pending.pop()
            continue
        if isinstance(item, str):
            encoded += 256+32*len(item)
        elif isinstance(item, dict):
            encoded += 256+64*len(item)
            pending.append(iter(item.values()))
        elif isinstance(item, (list, tuple)):
            encoded += 128+64*len(item)
            pending.append(iter(item))
            cells += 1
        if encoded > selected.available_bytes or cells > 8*MAX_CELLS:
            raise MemoryLimitError('encoded exact material exceeds its caller workspace budget')
    with selected.reserve(encoded, category='i03-exact-restore'), geometry_workspace(budget):
        return _restore(record)


def _restore(record):
    try:
        if not isinstance(record, dict):
            raise SupportError('material support record must be a mapping')
        extended = record.get('schema') == BUDGET_SCHEMA
        keys = {'schema', 'patches', 'coordinate_bits', 'coordinate_encoding'} if extended else {'schema', 'patches'}
        if set(record) != keys or record['schema'] not in (SCHEMA, DENSITY_SCHEMA, BUDGET_SCHEMA):
            raise SupportError('unsupported material support schema')
        if extended and (type(record['coordinate_bits']) is not int or record['coordinate_bits'] <= LEGACY_COORDINATE_BITS
                         or record['coordinate_encoding'] != 'decimal-or-hex-v1'):
            raise SupportError('invalid material coordinate encoding bound')
        def coordinate(value):
            if type(value) is not str:
                raise SupportError('stored coordinates are canonical integer strings')
            hexadecimal = value.startswith(('0x', '-0x'))
            if not extended and (hexadecimal or len(value) > 1235):
                raise SupportError('legacy material coordinate exceeds its schema bound')
            result = int(value, 16 if hexadecimal else 10)
            limit = record['coordinate_bits'] if extended else LEGACY_COORDINATE_BITS
            if abs(result).bit_length() > limit:
                raise SupportError('stored material coordinate exceeds its declared bound')
            return result
        patches = []
        for row in record['patches']:
            if len(row) not in ((5,) if record['schema'] == SCHEMA else (5, 6)):
                raise SupportError('unsupported material patch record')
            face, cohort, cells, stock, allowance = row[:5]
            density = None if len(row) == 5 else tuple(Fraction(int(n), int(d)) for n, d in row[5])
            patches.append(Patch(face, cohort, tuple(tuple(tuple(coordinate(v) for v in p) for p in cell) for cell in cells),
                                 tuple(Fraction(int(n), int(d)) for n, d in stock), allowance, density))
        result = Support(tuple(patches))
        if result.record() != record:
            raise SupportError('material support does not reproduce its exact representation')
        return result
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as exc:
        raise SupportError('invalid material support record') from exc


def reconcile(patches, keys, stock, *, signed=False):
    """Assign only the piece's already-booked final rounding to its largest patch."""
    by_key = {}
    for patch in patches:
        by_key.setdefault((patch.face_id, patch.cohort_id), []).append(patch)
    out = []
    for key, values in zip(keys, stock):
        pieces = by_key.pop(key, [])
        if not pieces:
            raise SupportError('an endpoint piece has no material footprint')
        k = max(range(len(pieces)), key=lambda i: pieces[i].stock[0])
        delta = [Fraction(float(v))-sum((p.stock[j] for p in pieces), Fraction(0)) for j, v in enumerate(values)]
        adjusted = tuple(a+d for a, d in zip(pieces[k].stock, delta))
        if adjusted[0] <= 0 or any(v < 0 for v in adjusted[1:-1 if signed else None]):
            raise SupportError('piece rounding would erase a positive material patch')
        pieces[k] = replace(pieces[k], stock=adjusted,
                            area_allowance_m2=upper(Fraction(pieces[k].area_allowance_m2)+abs(delta[0])))
        out.extend(pieces)
    if by_key:
        raise SupportError('a material footprint has no endpoint piece')
    return Support(tuple(sorted(out, key=lambda p: (p.face_id, p.cohort_id, p.patch_id))))


def completed_rows(network, endpoint, rows, *, sweeps=(), budget=None, cancel=None, precise=None):
    """Complete exact positive candidates omitted by the projected evidence map.

    This transient map is recomputed on replay; it does not replace the stored
    authenticated measurement. Cap padding only broadens candidate selection,
    using the existing atlas-index 256-epsilon rule; exact clipping decides zero.
    """
    from scipy.spatial import cKDTree
    T = _tools()
    before, after, donors, receivers = T._changed(network, endpoint)
    # A ridge can rename a riding corner without changing any local direction.
    # The original motion producer correctly issues no material row there.
    # Candidate completion must not turn that identity into a newly measured
    # clip and thereby discard its inherited event occupancy allowance.
    issued = {source for source in rows.donor if source >= 0}
    targets = {name: i for i, name in enumerate(endpoint.face_ids)}
    riding = {}
    for source in donors:
        name = network.face_ids[source]
        if source in issued or name not in targets:
            continue
        target = targets[name]
        a, b = before.rings(source), after.rings(target)
        if (network.face_plate(name) == endpoint.face_plate(name) and len(a) == len(b)
                and all(np.array_equal(x, y) for x, y in zip(a, b))):
            riding[source] = target
    donors = [source for source in donors if source not in riding]
    rode = set(riding.values())
    receivers = [target for target in receivers if target not in rode]
    if not donors:
        return rows
    born = {target for source, target in zip(rows.donor, rows.receiver) if source < 0}
    entries = []
    for target in receivers:
        if target not in born:
            rings = after.rings(target)
            entries.append((endpoint.face_plate(endpoint.face_ids[target]), target, None, rings))
    for boundary, plate, ring in sweeps:
        entries.append((plate, -1, 'trench|'+boundary, (ring,)))
    if not entries:
        return rows
    allowance = 65536+2048*(len(entries)+len(donors))
    with T.select_budget(budget).reserve(allowance, category='i03-material-candidate-index'):
        groups, data = {}, []
        for plate, target, party, rings in entries:
            centre, radius = T._cap(rings)
            if radius >= math.pi/2:
                raise SupportError('exact material candidate cap is not hemispherical')
            index = len(data)
            data.append((target, party, rings, centre, radius))
            bucket = math.ceil(math.log2(max(radius, np.finfo(float).eps)))
            groups.setdefault((plate, bucket), []).append(index)
        trees = {}
        for (plate, _), indices in groups.items():
            centres = np.asarray([data[i][3] for i in indices])
            trees.setdefault(plate, []).append((cKDTree(centres, copy_data=True), tuple(indices),
                                                max(data[i][4] for i in indices)))
        existing = {(source, target, None if party < 0 else rows.parties[party])
                    for source, target, party in zip(rows.donor, rows.receiver, rows.party) if source >= 0}
        cell_cache, added = {}, {}
        padding = 256*np.finfo(float).eps
        for source in donors:
            T._check_cancel(cancel)
            rings = before.rings(source)
            centre, radius = T._cap(rings)
            if radius >= math.pi/2:
                raise SupportError('exact material donor cap is not hemispherical')
            own = None
            plate = network.face_plate(network.face_ids[source])
            for tree, indices, maximum in trees.get(plate, ()):
                reach = 2*math.sin(min(math.pi, radius+maximum)/2)+padding
                for local in sorted(tree.query_ball_point(centre, reach, workers=1)):
                    index = indices[local]
                    target, party, other_rings, other_centre, other_radius = data[index]
                    key = source, target, party
                    if key in existing:
                        continue
                    chord = 2*math.sin(min(math.pi, radius+other_radius)/2)+padding
                    if np.linalg.norm(centre-other_centre) > chord:
                        continue
                    if own is None:
                        own = cells_of_rings(rings)
                    if index not in cell_cache:
                        if precise is not None and target >= 0 and target in precise[0]:
                            cell_cache[index] = precise[0][target][0]
                        elif precise is not None and target < 0 and (party[len('trench|'):], plate) in precise[1]:
                            cell_cache[index] = precise[1][party[len('trench|'):], plate]
                        else:
                            cell_cache[index] = cells_of_rings(other_rings)
                    common = intersection(own, cell_cache[index])
                    if common:
                        added.setdefault(key, []).extend(common)
                    if len(existing)+len(added) > T.MAX_ROWS:
                        raise SupportError('exact material candidates exceed the existing row limit')
        if not added:
            return rows
        donor, receiver, party, area, parties = (list(rows.donor), list(rows.receiver), list(rows.party),
                                                list(rows.area_m2), list(rows.parties))
        for (source, target, label), cells in sorted(added.items()):
            value = area_sr(tuple(sorted(set(cells))))*network.sphere.radius_m**2
            if not value > 0:
                raise SupportError('positive exact material candidate has unrepresentable area')
            donor.append(source)
            receiver.append(target)
            if label is not None and label not in parties:
                parties.append(label)
            party.append(-1 if label is None else parties.index(label))
            area.append(value)
        return T._Rows(tuple(donor), tuple(receiver), tuple(party), tuple(area), tuple(parties), rows.transient)


def row_fragments(network, material, endpoint, rows, *, sweeps=(), cancel=None, precise=None):
    """Sparse patch/row intersections; a row is only a candidate, never a cohort weight."""
    T = _tools()
    support = required(material)
    shapes = T._Shapes(endpoint)
    receiver_cells = {}
    sweep_cells = {}
    for boundary, plate, ring in sweeps:
        sweep_cells.setdefault((boundary, plate), []).extend(cells_of_rings((ring,)))
    if precise is not None:
        sweep_cells.update(precise[1])
    donors = {}
    for row, source in enumerate(rows.donor):
        if source >= 0:
            donors.setdefault(network.face_ids[source], []).append(row)
    out = []
    for patch in support.patches:
        T._check_cancel(cancel)
        if patch.face_id not in donors:
            out.append((patch, None, patch.cells, float(patch.stock[0])))
            continue
        pieces = []
        for row in donors[patch.face_id]:
            target = rows.receiver[row]
            if target >= 0:
                if target not in receiver_cells:
                    receiver_cells[target] = (precise[0][target][0] if precise is not None and target in precise[0]
                                              else cells_of_rings(shapes.rings(target)))
                cells = receiver_cells[target]
            else:
                boundary = rows.parties[rows.party[row]][len('trench|'):]
                plate = network.face_plate(patch.face_id)
                cells = tuple(sweep_cells.get((boundary, plate), ()))
                if not cells:
                    raise SupportError('trench material selection requires its actual swept geometry')
            common = intersection(patch.cells, cells)
            if common:
                area = area_sr(common)*network.sphere.radius_m**2
                if not area > 0:
                    raise SupportError('positive material intersection has unrepresentable area')
                pieces.append((patch, row, common, area))
        measured = area_sr(patch.cells)*network.sphere.radius_m**2
        total = math.fsum(p[3] for p in pieces)
        if abs(total-measured) > T.RELATIVE_TOLERANCE*measured:
            raise SupportError('material intersections do not partition their donor within the existing tolerance')
        out.extend(pieces)
    return tuple(out)


def renamed(support, mapping):
    return Support(tuple(replace(p, cohort_id=mapping.get((p.face_id, p.cohort_id), p.cohort_id))
                         for p in support.patches))


def _projective_reexpression(before, after, face_id, turn):
    """Exact triangle maps, admitted under the existing four-epsilon displacement bound."""
    from . import integration_events as E
    T = _tools()
    rings = T._Shapes(before).rings(before.face_ids.index(face_id))
    next_rings = T._Shapes(after).rings(after.face_ids.index(face_id))
    if len(rings) != 1 or len(next_rings) != 1:
        raise SupportError('internal-cut event re-expression needs a matching constrained triangulation for holes')
    old_float, new_float = rings[0], next_rings[0]
    old_integer, new_integer = T._integers(old_float), T._integers(new_float)
    indices = {T._primitive(p): i for i, p in enumerate(old_integer)}
    centre = T._integers([T._sphere._mean_direction(np.asarray(old_float))])[0]
    triangles = tuple(_canonical(c) for c in T._exact_triangles(old_float, centre))
    # The rational quaternion formula is exactly orthogonal after dividing by
    # q.q; include matrix-formation/placement rounding in d, not outside C10.
    w, x, y, z = (Fraction(v) for v in turn.quaternion)
    norm = w*w+x*x+y*y+z*z
    matrix = tuple(tuple(v/norm for v in row) for row in (
        (w*w+x*x-y*y-z*z, 2*(x*y-w*z), 2*(x*z+w*y)),
        (2*(x*y+w*z), w*w-x*x+y*y-z*z, 2*(y*z-w*x)),
        (2*(x*z-w*y), 2*(y*z+w*x), w*w-x*x-y*y+z*z)))
    prepared, mapped = [], []
    for triangle in triangles:
        selected = [indices[p] for p in triangle]
        source = tuple(old_integer[i] for i in selected)
        target = tuple(new_integer[i] for i in selected)
        ideal = [tuple(sum((matrix[k][j]*Fraction(float(old_float[i][j])) for j in range(3)), Fraction(0))
                       for k in range(3)) for i in selected]
        normal = tuple(Fraction(float(v)) for v in T._sphere._mean_direction(np.asarray(ideal, dtype=float)))
        c = min(T._dot(normal, p) for p in ideal)
        d2 = max(sum(((Fraction(float(new_float[i][k]))-p[k])**2 for k in range(3)), Fraction(0))
                 for i, p in zip(selected, ideal))
        if c <= 0:
            raise SupportError('event triangle has no conditioned common hemisphere')
        eta2 = d2*T._dot(normal, normal)/(c*c)
        eta = math.sqrt(float(eta2))
        while Fraction(eta)**2 < eta2:
            eta = math.nextafter(eta, math.inf)
        ratio = Fraction(eta)
        if ratio >= 1 or ratio/(1-ratio) > Fraction(E.REEXPRESSION_ROUNDING):
            raise SupportError('internal-cut event re-expression exceeds the existing four-epsilon angular bound')
        determinant = T._dot(source[0], T._cross(source[1], source[2]))
        cofactors = (T._cross(source[1], source[2]), T._cross(source[2], source[0]),
                     T._cross(source[0], source[1]))
        prepared.append((triangle, target, cofactors, T._sign(determinant)))
        mapped.append(_canonical(target))
    own = cells_of_rings(next_rings)
    if difference(tuple(mapped), own) or difference(own, tuple(mapped)):
        raise SupportError('internal-cut event needs an exactly matching successor face triangulation')
    return tuple(prepared)


@_bounded_geometry(scratch_inputs=27)
def _projectively_carried(patch, prepared, radius):
    from . import integration_events as E
    T = _tools()
    cells, area_bound = [], 0.
    for triangle, target, cofactors, sign in prepared:
        for original in patch.cells:
            cell = intersect_cell(original, triangle)
            if not cell:
                continue
            mapped = []
            for point in cell:
                weights = tuple(T._dot(point, cofactor)*sign for cofactor in cofactors)
                if any(w < 0 for w in weights):
                    raise SupportError('a clipped event point has a negative projective coefficient')
                mapped.append(T._primitive(tuple(sum(weights[j]*target[j][k] for j in range(3))
                                                for k in range(3))))
            carried = _canonical(tuple(mapped))
            if not carried:
                raise SupportError('event re-expression would erase a positive material cell')
            cells.append(carried)
            bound = E._reexpression_bound((directions(cell),), (directions(carried),),
                                          area_sr((carried,))*radius**2, radius,
                                          perimeter=perimeter_rad(carried))
            area_bound = None if area_bound is None or bound is None else math.fsum((area_bound, bound))
    cells = tuple(sorted(set(cells)))
    old_area, new_area = area_sr(patch.cells)*radius**2, area_sr(cells)*radius**2
    delta = abs(Fraction(old_area)-Fraction(new_area))
    allowance = patch.area_allowance_m2
    if area_bound is not None:
        if delta > Fraction(area_bound):
            raise SupportError('material event re-expression exceeds its existing D7 geometry bound')
        allowance = upper(Fraction(allowance)+delta)
    return replace(patch, cells=cells, area_allowance_m2=allowance)


def reexpressed(before, after, support):
    """Frame changes preserve named vertex identity, not a second normalised copy."""
    T = _tools()
    old, new = dict(before._layout.frames), dict(after._layout.frames)
    before_index = {name: i for i, name in enumerate(before._layout.names)}
    after_index = {name: i for i, name in enumerate(after._layout.names)}
    before_plate = {name: i for i, name in enumerate(before.plate_ids)}
    after_plate = {name: i for i, name in enumerate(after.plate_ids)}
    correspondence, projective = {}, {}
    patches = []
    for patch in support.patches:
        a, b = before.face_plate(patch.face_id), after.face_plate(patch.face_id)
        key = a, b
        if key not in correspondence:
            table = {}
            for name in before_index.keys() & after_index.keys():
                p = before._local[before_plate[a]][before_index[name]]
                q = after._local[after_plate[b]][after_index[name]]
                if np.isfinite(p).all() and np.isfinite(q).all():
                    table[T._primitive(T._integers([p])[0])] = T._primitive(T._integers([q])[0])
            correspondence[key] = table
        table = correspondence[key]
        unchanged_frame = old[a].quaternion == new[b].quaternion
        turn = old[a].then(new[b].inverse())
        changes_coordinates = not unchanged_frame or any(point != table.get(point, point)
                                                         for cell in patch.cells for point in cell)
        if changes_coordinates and any(point not in table for cell in patch.cells for point in cell):
            if patch.face_id not in projective:
                projective[patch.face_id] = _projective_reexpression(before, after, patch.face_id, turn)
            patches.append(_projectively_carried(patch, projective[patch.face_id], before.sphere.radius_m))
            continue
        cells = []
        for cell in patch.cells:
            carried = []
            for point in cell:
                if point in table:
                    carried.append(table[point])
                elif unchanged_frame:
                    carried.append(point)
                else:
                    carried.append(T._primitive(T._integers(T._turned(turn, directions((point,))))[0]))
            cells.append(_canonical(tuple(carried)))
        patches.append(replace(patch, cells=tuple(cells)))
    return Support(tuple(patches))


@dataclass(frozen=True)
class TraceSegment:
    start_direction: tuple
    end_direction: tuple
    left_piece: tuple
    right_piece: tuple
    left_patch: str
    right_patch: str


def piece_footprints(sphere, face_id, cohort_id, *, world=True):
    patches = required(sphere.material).patches_of_piece(face_id, cohort_id)
    frame = dict(sphere.network._layout.frames)[sphere.network.face_plate(face_id)]
    return tuple(_tools()._turned(frame, directions(cell)) if world else directions(cell)
                 for patch in patches for cell in patch.cells)


def require_uniform_column(sphere, piece_key, patch_id):
    """Admit the selected patch only if a piece-wide mechanical column is valid.

    This is an exact claim about retained mass/area and volume/area, never about
    I03's unrelated enthalpy basis. I05 separately establishes thermal uniformity
    when it declares/transports its own heat. Refusal is deliberately conservative.
    """
    material = sphere.material
    patches = required(material).patches_of_piece(*piece_key)
    if not patches or patch_id not in {p.patch_id for p in patches}:
        raise SupportError('a trace patch is not part of the requested piece')
    width = 1+2*len(material.phases)
    densities = {tuple(v/p.stock[0] for v in p.stock[1:width]) for p in patches}
    if len(densities) != 1:
        raise SupportError('a piece contains different patch mass/volume columns; piece-wide evaluation is unresolved')
    return None


def material_trace_segments(sphere):
    """Ordered sided material intersections of each original boundary edge.

    The trace is partitioned by exact convex half-plane inequalities in each
    plate frame. Original endpoints and each shared interior cut are emitted
    once, ensuring bitwise joins for consumers. A coincident material interface
    is resolved by the face-side interior; ambiguous positive-length ownership
    refuses rather than picking a cohort by name.
    """
    T = _tools()
    network, support = sphere.network, required(sphere.material)
    vertex = dict(zip(network.vertex_ids, network.vertex_direction))
    local_index = {name: i for i, name in enumerate(network._layout.names)}
    owners, patches_of = {}, {}
    for face in network.faces:
        for ring in (face.vertex_ids, *face.holes):
            for a, b in zip(ring, ring[1:]+ring[:1]):
                if (a, b) in owners:
                    raise SupportError('a directed material trace edge has multiple face owners')
                owners[a, b] = face.face_id
    for patch in support.patches:
        patches_of.setdefault(patch.face_id, []).append(patch)
    out = []
    for boundary in network.boundaries:
        ids = boundary.vertex_ids
        edges = list(zip(ids, ids[1:]))+([(ids[-1], ids[0])] if boundary.closed else [])
        for start, end in edges:
            a, b = vertex[start], vertex[end]
            contacts, cuts = [], {Fraction(0), Fraction(1)}
            for side_index, plate in enumerate((boundary.left_plate_id, boundary.right_plate_id)):
                face = owners.get((start, end) if side_index == 0 else (end, start))
                if face is None or network.face_plate(face) != plate:
                    raise SupportError('boundary material candidates do not match the directed face owner')
                local = network._local[network.plate_ids.index(plate)][[local_index[start], local_index[end]]]
                u, v = T._integers(local)
                trace_normal = T._cross(u, v)
                side = []
                for patch in patches_of.get(face, ()):
                    for cell in patch.cells:
                        low, high = Fraction(0), Fraction(1)
                        coincident = False
                        for p, q in zip(cell, cell[1:]+cell[:1]):
                            n = T._cross(p, q)
                            x, y = T._dot(n, u), T._dot(n, v)
                            coincident |= x == y == 0
                            if x < 0 and y < 0:
                                high = low
                                break
                            if x < 0 <= y:
                                low = max(low, Fraction(-x, y-x))
                            elif y < 0 <= x:
                                high = min(high, Fraction(x, x-y))
                        # On a coincident interface only the inward material is
                        # adjacent; a closed polygon on the other side is not.
                        inward = sum(T._sign(T._dot(trace_normal, p)) for p in cell)
                        admitted_side = not coincident or (inward > 0 if side_index == 0 else inward < 0)
                        if high > low and admitted_side:
                            side.append((low, high, patch))
                            cuts.update((low, high))
                contacts.append(side)
            ordered = sorted(cuts)
            points = {Fraction(0): tuple(float(x) for x in a), Fraction(1): tuple(float(x) for x in b)}
            for cut in ordered[1:-1]:
                point = (1-float(cut))*a+float(cut)*b
                point /= np.linalg.norm(point)
                points[cut] = tuple(float(x) for x in point)
            segments = []
            for lo, hi in zip(ordered, ordered[1:]):
                mid = (lo+hi)/2
                selected = []
                for side in contacts:
                    matches = {p.patch_id: p for left, right, p in side if left < mid < right}
                    if len(matches) != 1:
                        raise SupportError('a boundary trace has missing or ambiguous sided material support')
                    selected.append(next(iter(matches.values())))
                left, right = selected
                segments.append(TraceSegment(points[lo], points[hi], (left.face_id, left.cohort_id),
                                             (right.face_id, right.cohort_id), left.patch_id, right.patch_id))
            out.append(tuple(segments))
    return tuple(out)
