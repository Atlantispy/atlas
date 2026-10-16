"""GMP-resident twins of exact geometry kernels.

Complete operations: convex clipping and volume (the algorithms of
integration_volume_bounds._box/_clip/_volume) and the Rodrigues projection
enclosure (integration_cone_zero.projection_bounds with its alternating
series), exterior-mesh cell closure, and mimetic first moments. Each is the
reference algorithms with equivalent exact predicates, on gmpy2
mpq/mpz values in place of Fraction/int. Every intermediate is the same
canonical rational; classification uses the same integer numerators; faces,
caps, vertex order and series terms come from the same exact predicates and
field operations. No floating value, tolerance, rounding or reduced precision
exists here. An operation converts its inputs (_box, _native), keeps its
intermediates native, and converts only what leaves it (_exact, _barycentre).
A native value is never stored, hashed into an identity, encoded or returned
through a public interface.

Admission for clipping, volume and projection. Predicate work is counted from the same vertex and face counts, and
every byte reservation of the reference route is made here for the same
amount, in the same category and order: for one operation, work units and
those reservations do not depend on the route. Each step's arithmetic lease is
taken before that step's native intermediates are built; a plane's integer row
is built inside it and dropped with it. The retained-scratch formula was
written for Python objects, and gmpy2 can hold a small rational on a large
recycled block, so each retained native coordinate is first brought onto a
bounded block (_settle) and the difference between that bound and the
reference allowance is reserved as well, in its own category (grouped as
'other' on a ledger that already names 63). That surcharge only adds: the GMP
route never admits what the Python route refuses. A failed
GMP allocation ends the process and cannot be unwound, which is why nothing
here relies on catching one (docs/EXACT_ARITHMETIC_BACKEND.md).

Cell closure and mimetic moments add advance arithmetic and native working-set leases;
the Python oracle had no inner lease. No new native operation starts before
both admit. Successful closure clears its native values before returning the
leases; a failed operation keeps them charged while its exception or traceback
retains its frames, using the existing escaping-workspace owner.

This module always imports. Without the selected library its functions are
unreachable: integration_volume_bounds._resident never returns it, and
integration_cone_zero asks that same rule.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from fractions import Fraction
from itertools import product
import sys

from . import exact_arithmetic as X
from . import integration_volume as V
from . import integration_volume_overlap as O
from .integration_volume_bounds import _BOX_RINGS, NATIVE_RETAINED, _ScalarSum

# This wheel counts bits in 32 bits: a value crossing 2**32 bits reports a wrong
# bit length or ends the process. One admitted step's operands are refused long
# before its results could reach that; the Python route has no such limit.
CEILING_BITS = 1 << 27
# Measured for gmpy2 2.3.2: a freed object is reused with its limb blocks when
# each holds at most 64 allocated limbs, and a result keeps the block its own
# intermediates needed. _settle therefore bounds the two blocks of a retained
# coordinate TOGETHER by the sum, over numerator and denominator, of
# max(RECYCLED_LIMBS, limbs needed + 2) limbs (cap). OBJECT_BYTES is the
# allowance for everything that is not limbs (the object, two block headers and
# allocator rounding) while the surcharge is positive, which requires blocks of
# about 1 KB or less; the most measured there was about 115 bytes. A wider
# value is covered by the reference allowance, which grows with its payload.
RECYCLED_LIMBS = 64
OBJECT_BYTES = 160
HEADER_BYTES = 72

_library = X.library()
if _library is not None:
    mpq, mpz = _library.mpq, _library.mpz
    _numer, _denom, _lcm, _gcd = _library.numer, _library.denom, _library.lcm, _library.gcd
    _zero, _one = mpq(0), mpq(1)
_sizeof = sys.getsizeof


class _Poly(tuple):
    """Outward faces of native points, alive only inside one operation.

    points  the sorted distinct vertices (the Python route's _points);
    info    per vertex: summed rational bit length, summed payload bytes and
            native surcharge of its three coordinates;
    bits, quarters, extra  their totals over points;
    unpaid  surcharge of a box not yet charged to an owning arena (_own).
    """


class _Plane:
    """normal.x <= limit, held as the caller's exact entries.

    bits is their admission width, so an integer plane is charged exactly as
    the Python route charges it. The integer row is native and is built only
    inside an admitted step (_row).
    """
    __slots__ = ('source', 'bits', 'cuts', 'admits_all')


def _native(value):
    if type(value) is Fraction:
        return mpq(value.numerator, value.denominator)
    if type(value) is int:
        return mpq(value)
    raise V.VolumeError('exact int or Fraction required at the native boundary')


def _exact(value):
    """A Fraction holding Python ints; never a Fraction wrapped around mpz."""
    if type(value) is Fraction:
        if type(value.numerator) is int and type(value.denominator) is int:
            return value
        return Fraction(int(value.numerator), int(value.denominator))
    return Fraction(int(_numer(value)), int(_denom(value)))


def _bits(value):
    return max(1, _numer(value).bit_length()+_denom(value).bit_length())


def _total(values):
    return sum(values, _zero)


def _plane(plane):
    if len(plane) != 4 or any(type(v) is not int and type(v) is not Fraction for v in plane):
        raise V.VolumeError('exact int or Fraction plane required at the native boundary')
    result = object.__new__(_Plane)
    result.source = tuple(plane)
    result.bits = sum(V._bits(v) for v in plane)
    result.cuts = any(plane[:3])
    result.admits_all = plane[3] >= 0
    return result


def _negated(plane):
    """The opposite halfspace; bit lengths do not depend on sign."""
    result = object.__new__(_Plane)
    result.source = tuple(-v for v in plane.source)
    result.bits, result.cuts = plane.bits, plane.cuts
    result.admits_all = plane.source[3] <= 0
    return result


def _row(plane):
    """The plane over one positive common denominator, as native integers.

    Called only inside a lease that has admitted the plane's entries.
    """
    source = plane.source
    common = _lcm(*(mpz(v.denominator) for v in source))
    return tuple(mpz(v.numerator)*(common//v.denominator) for v in source), common


def _settle(point):
    """One retained point on bounded blocks, with its admission row.

    Returns the point (the same value) and (bits, payload bytes, surcharge).
    A coordinate whose two blocks together exceed the bound is rebuilt from
    its integers; the surcharge is what that bound exceeds the reference
    allowance of 128 bytes plus four payload copies per value.
    """
    bits = quarters = extra = 0
    settled = None
    for index, q in enumerate(point):
        n, d = _numer(q), _denom(q)
        nb, db = n.bit_length(), d.bit_length()
        cap = 8*(max(RECYCLED_LIMBS, (nb+63)//64+2)+max(RECYCLED_LIMBS, (db+63)//64+2))
        if _sizeof(q) > HEADER_BYTES+cap:
            q = mpq(int(n), int(d))
            cap = max(cap, _sizeof(q)-HEADER_BYTES)
            if settled is None:
                settled = list(point)
            settled[index] = q
        width = max(1, nb+db)
        payload = (width+7)//8
        bits += width
        quarters += payload
        extra += max(0, OBJECT_BYTES+cap-128-4*payload)
    return (point if settled is None else tuple(settled)), (bits, quarters, extra)


def _poly(faces, known, fresh):
    points = tuple(sorted({p for face in faces for p in face}))
    info, bits, quarters, extra = {}, 0, 0, 0
    for point in points:
        row = known.get(point)
        if row is None:
            row = fresh[point]
        info[point] = row
        bits += row[0]
        quarters += row[1]
        extra += row[2]
    poly = _Poly(faces)
    poly.points, poly.info, poly.bits, poly.quarters = points, info, bits, quarters
    poly.extra, poly.unpaid = extra, 0
    return poly


def _points(poly):
    return poly.points if poly else ()


def _retained_extra(polys):
    """Native surcharge of polyhedra a caller keeps alive beyond their arena."""
    return sum(poly.extra for poly in polys if poly)


def _box(cell):
    """integration_volume_bounds._box on the same exact cell geometry.

    Low-level constructor: the caller holds an arithmetic lease for the cell
    (_owned_box, or _bound_leaf's existing outer lease). Its native surcharge
    is transferred to that caller's arena before the lease is released.
    """
    origin = tuple(map(_native, cell.origin_m))
    basis = tuple(tuple(map(_native, row)) for row in cell.basis)
    lower, upper = tuple(map(_native, cell.lower_m)), tuple(map(_native, cell.upper_m))
    points, fresh = [], {}
    for local in product(*zip(lower, upper)):
        point, row = _settle(tuple(o+sum((b*q for b, q in zip(row, local)), _zero)
                                   for o, row in zip(origin, basis)))
        fresh[point] = row
        points.append(point)
    reflected = O._dot(cell.basis[0], O._cross(cell.basis[1], cell.basis[2])) < 0
    faces = []
    for indices in _BOX_RINGS:
        if reflected:
            indices = indices[::-1]
        ring = tuple(points[i] for i in indices)
        start = min(range(4), key=ring.__getitem__)
        faces.append(ring[start:]+ring[:start])
    poly = _poly(tuple(faces), {}, fresh)
    poly.unpaid = poly.extra
    return poly


def _own(poly, arena):
    """Charge a box's native surcharge to the arena that will hold it."""
    if poly and poly.unpaid:
        arena._retain(poly.unpaid, NATIVE_RETAINED)
        poly.unpaid = 0


def _arithmetic(values, resource):
    return _work(sum(V._bits(v) if type(v) in (int, Fraction) else _bits(v)
                     for v in values), len(values), resource)


def _owned_box(cell, arena):
    with _arithmetic(cell._geometry(), arena.resource):
        poly = _box(cell)
        size = 1024+384*len(poly.points)+128*sum(map(len, poly))+4*poly.quarters
        with ExitStack() as pending:
            pending.enter_context(arena.resource.reserve(size, category='curved-volume-scratch'))
            _own(poly, arena)
            arena.stack.enter_context(pending.pop_all())
        return poly


def _scalar_memory(value):
    (value,), (_, payload, extra) = _settle((value,))
    return value, 128+4*payload, extra


def _total_volumes(polys, arena):
    with _ScalarSum(sys.modules[__name__], arena) as total:
        for poly in polys:
            # Consume the result before _volume releases its arithmetic lease.
            _volume(poly, arena, _consume=total.add)
        return total.exact()


def _volume_exact(poly, arena):
    return _volume(poly, arena, _consume=_exact)


@contextmanager
def _work(bits, count, budget, *, pairs=0):
    # integration_volume._work's allowance for the same operands. Its name and
    # the bits/pairs locals are what a failure report reads from the traceback.
    with budget.reserve(65536+128*bits+256*count+256*pairs, category='i03-physical-volume'):
        if bits > CEILING_BITS:
            raise V.VolumeError('exact operands exceed the GMP route ceiling of 2**27 bits in one step; '
                                'use ATLAS_EXACT_ARITHMETIC=python')
        yield


def _face(vertices, indices, normal, *, _coplanar_cap=False):
    """integration_volume_overlap._face; normal may be any positive multiple."""
    omitted = max(range(3), key=lambda j: abs(normal[j]))
    x, y = (j for j in range(3) if j != omitted)
    ordered = sorted(indices, key=lambda i: (vertices[i][x], vertices[i][y]))

    def turn(i, j, k):
        p, q, r = vertices[i], vertices[j], vertices[k]
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
    if _coplanar_cap:
        # Only _clip sets this: cap points are exact intersections with this
        # nonzero plane (or already have exactly zero plane numerator).
        # Dropping its largest normal coordinate is injective on the plane.
        # The strict projected hull above is counterclockwise, so its signed
        # 3-D normal component is positive except when coordinate 1 is dropped.
        # Its cross is parallel to normal, hence their dot has this same sign.
        orientation = -normal[omitted] if omitted == 1 else normal[omitted]
    else:
        cross = O._cross(O._minus(vertices[ring[1]], vertices[ring[0]]),
                         O._minus(vertices[ring[2]], vertices[ring[0]]))
        orientation = normal[0]*cross[0]+normal[1]*cross[1]+normal[2]*cross[2]
    if orientation == 0:
        raise O.OverlapError('degenerate supporting face after exact hull ordering')
    if orientation < 0:
        ring.reverse()
    start = ring.index(min(ring))
    return tuple(ring[start:]+ring[:start])


def _noncollinear(p, q, r):
    """Exact nonzero-cross predicate, stopping at the first unequal product."""
    ax, ay, az = q[0]-p[0], q[1]-p[1], q[2]-p[2]
    bx, by, bz = r[0]-p[0], r[1]-p[1], r[2]-p[2]
    return ay*bz != az*by or az*bx != ax*bz or ax*by != ay*bx


def _numerators(points, coeff):
    """Sign-deciding numerators of integration_volume_bounds._plane_integer_rows."""
    c0, c1, c2, c3 = coeff
    for x, y, z in points:
        dx, dy, dz = _denom(x), _denom(y), _denom(z)
        den = _lcm(dx, dy, dz)
        yield c0*_numer(x)*(den//dx)+c1*_numer(y)*(den//dy)+c2*_numer(z)*(den//dz)-c3*den, den


def _clip(poly, plane, arena):
    """Exact convex-polyhedron clipping; only EXACT zero-volume faces vanish."""
    if not poly:
        return ()
    if type(poly) is not _Poly or type(plane) is not _Plane:
        raise TypeError('native-resident polyhedron and plane required')
    if not plane.cuts:
        return poly if plane.admits_all else ()
    _own(poly, arena)
    points = poly.points
    arena.work(16+8*len(points))
    with _work(poly.bits+plane.bits, 3*len(points)+4, arena.resource):
        coeff, common = _row(plane)
        # Every plane entry is an exact int/Fraction with positive denominator,
        # so common is positive. It cancels from both edge-plane distances in
        # t = na*db/(na*db-nb*da). Keep the OLD scaled-width guard below.
        rows = {point: (num, den) for point, (num, den) in zip(points, _numerators(points, coeff))}
        if max(row[0] for row in rows.values()) <= 0:
            return poly
        if min(row[0] for row in rows.values()) >= 0:
            return ()
        row_bytes = 256*len(rows)+4*sum((n.bit_length()+(common*d).bit_length()+7)//8
                                      for n, d in rows.values())
        cache_bytes = 1024+768*sum(map(len, poly))+row_bytes
        with arena.resource.reserve(cache_bytes, category='curved-clip-edge-cache'):
            intersections, fresh = {}, {}
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
                                t = mpq(numerator, numerator-nb*da)
                                point, row = _settle(tuple(a[j]+t*(b[j]-a[j]) for j in range(3)))
                                fresh[point] = row
                                intersections[a, b] = point
                                intersections[b, a] = point
                            out.append(point)
                            cap.add(point)
                    if len(out) >= 3:
                        unique = tuple(p for i, p in enumerate(out) if p != out[i-1])
                        if len(unique) >= 3 and any(_noncollinear(unique[0], unique[i], unique[i+1])
                                                    for i in range(1, len(unique)-1)):
                            faces.append(unique)
                cap = tuple(sorted(cap))
                if len(cap) >= 3:
                    ring = _face(cap, tuple(range(len(cap))), coeff, _coplanar_cap=True)
                    if ring is not None:
                        faces.append(tuple(cap[i] for i in ring))
                result = _poly(tuple(faces), poly.info, fresh)
                arena._retain(1024+384*len(result.points)+128*sum(map(len, result))
                              +4*result.quarters)
                if result.extra:
                    arena._retain(result.extra, NATIVE_RETAINED)
                return result or ()
            finally:
                intersections.clear()


def _repeat_volume_exact(poly, arena, known):
    """Replay admissions for a second volume of the SAME immutable polyhedron.

    Private leaf-only contract: known is the completed _volume_exact(poly)
    result still in that leaf's values list. The angular polyhedron is already
    retained by the original leaf; no additional graph or cache is created.
    Its first volume checked every face orientation, and clipping only returns
    this same object when it makes no change. Repeat all original work and
    byte admissions, in order, before reusing that already exact Fraction.
    """
    if not poly:
        return known
    if type(poly) is not _Poly:
        raise TypeError('native-resident polyhedron required')
    _own(poly, arena)
    points = poly.points
    arena.work(8+4*sum(map(len, poly)))
    with _work(poly.bits, 3*len(points), arena.resource):
        origin = points[0]
        bits = poly.bits+len(points)*poly.info[origin][0]
        storage = 1024+512*len(points)+4*((4*bits+8*len(points)+7)//8)
        with arena.resource.reserve(storage, category='curved-volume-integer-vectors'):
            return known


def _volume(poly, arena, *, _consume=None):
    if not poly:
        return _zero if _consume is None else _consume(_zero)
    if type(poly) is not _Poly:
        raise TypeError('native-resident polyhedron required')
    _own(poly, arena)
    points = poly.points
    arena.work(8+4*sum(map(len, poly)))
    with _work(poly.bits, 3*len(points), arena.resource):
        origin, six_volume = points[0], mpq(0)
        bits = poly.bits+len(points)*poly.info[origin][0]
        storage = 1024+512*len(points)+4*((4*bits+8*len(points)+7)//8)
        with arena.resource.reserve(storage, category='curved-volume-integer-vectors'):
            vectors = {}
            for point in points:
                if point == origin:
                    continue
                x, y, z = O._minus(point, origin)
                dx, dy, dz = _denom(x), _denom(y), _denom(z)
                den = _lcm(dx, dy, dz)
                vectors[point] = (_numer(x)*(den//dx), _numer(y)*(den//dy), _numer(z)*(den//dz)), den
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
                        six_volume += mpq(determinant, da*db*dc)
            result = six_volume/6
            return result if _consume is None else _consume(result)


def _barycentre(poly):
    """Exact vertex mean of a non-empty polyhedron, as Fractions."""
    vertices = poly.points
    return tuple(_exact(sum((v[j] for v in vertices), _zero)/len(vertices)) for j in range(3))


def _barycentre_admitted(poly, arena):
    with _work(poly.bits+V._bits(len(poly.points)), 3*len(poly.points)+1, arena.resource):
        return _barycentre(poly)


def _all_beyond(plane, points):
    """Every vertex has normal.x >= limit: exact halfspace broad phase.

    Called under the leaf's outer lease, which admits the plane. The vertices
    are those of the already retained polyhedron, as on the reference route.
    """
    coeff, _ = _row(plane)
    return all(num >= 0 for num, _ in _numerators(points, coeff))


def _all_within(plane, points):
    coeff, _ = _row(plane)
    return all(num <= 0 for num, _ in _numerators(points, coeff))


def _series(s, width, order, shift, arena):
    """integration_cone_zero._series: consecutive alternating partial sums."""
    total = term = _one
    for k in range(1, order+2):
        with _work(width+_bits(total)+_bits(term), 3, arena.resource):
            arena.work(32)
            term = -term*s/((2*k-1+shift)*(2*k+shift))
            previous, total = total, total+term
    return min(previous, total), max(previous, total)


def _projection_bounds(u, theta, g, arena, order):
    """integration_cone_zero.projection_bounds for validated int/Fraction vectors.

    Same admissions in the same order: the nine inputs at their int/Fraction
    widths, then (s, A, B, D), every series term, and the final products.
    Nothing is retained, so no surcharge arises.
    """
    with _work(sum(V._bits(x) for v in (u, theta, g) for x in v), 9, arena.resource):
        arena.work(96)
        u, theta, g = (tuple(map(_native, v)) for v in (u, theta, g))
        s = theta[0]*theta[0]+theta[1]*theta[1]+theta[2]*theta[2]
        value = u[0]*g[0]+u[1]*g[1]+u[2]*g[2]
        if not s:
            value = _exact(value)
            return value, value
        if s > 1:
            return None
        A = (u[0]*theta[0]+u[1]*theta[1]+u[2]*theta[2])*(theta[0]*g[0]+theta[1]*g[1]+theta[2]*g[2])/s
        cross = O._cross(theta, g)
        B, D = value-A, u[0]*cross[0]+u[1]*cross[1]+u[2]*cross[2]
    width = _bits(s)
    with _work(width+_bits(A)+_bits(B)+_bits(D), 4, arena.resource):
        if B == D == 0:
            A = _exact(A)
            return A, A
        cosine, sinc = _series(s, width, order, 0, arena), _series(s, width, order, 1, arena)
        with _work(sum(map(_bits, (A, B, D, *cosine, *sinc))), 7, arena.resource):
            arena.work(32)
            bc = sorted(B*x for x in cosine)
            ds = sorted(D*x for x in sinc)
            return _exact(A+bc[0]+ds[0]), _exact(A+bc[1]+ds[1])


def _mesh_closure_allowance(terms, volume):
    """Advance bounds for one cell's integer closure, without native allocation.

    Each row has twelve integer numerators and a positive common denominator.
    D bounds every denominator product. A group's numerator is bounded by its
    largest input numerator, the group's denominator bits and its sum count.
    Four full generations cover input/merged rows plus lingering last-pair
    references. Integer storage also allows the tested 64-limb recycled block
    and two spare limbs; the arithmetic lease separately covers GMP work space.
    """
    if type(volume) is not Fraction or type(volume.numerator) is not int or type(volume.denominator) is not int:
        raise V.VolumeError('plain Fraction volume required for native mesh closure')
    numerator_bits = denominator_bits = widest = 0
    for row, denominator in terms:
        if (len(row) != 12 or type(denominator) is not int or denominator <= 0 or
                any(type(value) is not int for value in row)):
            raise V.VolumeError('twelve integer terms and positive denominator required for native mesh closure')
        denominator_bits += denominator.bit_length()
        for value in row:
            width = max(1, value.bit_length())
            numerator_bits += width
            widest = max(widest, width)
    count = len(terms)
    growth = max(1, count.bit_length())+1
    volume_bits = max(1, volume.numerator.bit_length())+volume.denominator.bit_length()
    # The extra denominator product covers unreduced multiplication temporaries;
    # final comparisons also multiply by a volume numerator or denominator.
    product_bits = widest+2*denominator_bits+growth+volume_bits+8
    bits = numerator_bits+denominator_bits+volume_bits+product_bits
    generation_bits = numerator_bits+13*denominator_bits+12*count*growth
    slots = 4*(13*count+2)+32
    native_bytes = (1024+512*(count+1)+(4*generation_bits+volume_bits+7)//8
                    +slots*(OBJECT_BYTES+8*(RECYCLED_LIMBS+2)))
    return bits, 13*count+2, native_bytes


def _mesh_closure_fails(terms, volume, budget):
    """Complete admitted twin of exterior_mesh._closure_fails; only bool leaves.

    Python face-distance checks have already run. Both admissions precede all
    mpz conversion; a native refusal propagates, never selecting another route.
    The native working set is temporary; an escaping failure retains its charge.
    """
    from .integration_spatial_transport import _preserve_workspace

    bits, count, native_bytes = _mesh_closure_allowance(terms, volume)
    with ExitStack() as admitted:
        admitted.enter_context(_work(bits, count, budget))
        admitted.enter_context(budget.reserve(native_bytes, category='exact-native-mesh-closure'))
        merged = a = b = da = db = shared = wa = wb = None
        try:
            native = [([mpz(value) for value in row], mpz(denominator)) for row, denominator in terms]
            native.sort(key=lambda term: term[1])
            while len(native) > 1:
                merged = []
                for at in range(0, len(native)-1, 2):
                    (a, da), (b, db) = native[at], native[at+1]
                    shared = _gcd(da, db)
                    wa, wb = db//shared, da//shared
                    merged.append(([a[k]*wa+b[k]*wb for k in range(12)], da*wa))
                native = merged+native[2*len(merged):]
            totals, scale = native[0] if native else ([0]*12, 1)
            failed = bool(any(totals[:3]) or any(
                totals[3+3*i+j]*volume.denominator != (volume.numerator*scale if i == j else 0)
                for i in range(3) for j in range(3)))
            del native, merged, a, b, da, db, shared, wa, wb, totals, scale
            return failed
        except BaseException as error:
            # This local also owns the leases when only the traceback survives,
            # including native arguments retained by an instrumented callback.
            _failure_owner = _preserve_workspace(error, admitted)
            raise


def _mimetic_moment_allowance(vectors, centres, indexes, volume):
    """Bound one cell's native centroid moments before converting any value.

    Summed denominator widths bound every product denominator and partial sum;
    twice that bound also covers unreduced cross-products during addition.
    Native inputs retain two blocks per rational, including recycled limbs.
    Eight product payloads and sixteen extra rational slots cover the current
    product, sum and comparison temporaries; _work admits GMP workspace too.
    """
    if len(vectors) != len(indexes):
        raise V.VolumeError('one face index per mimetic vector required')
    width = denominators = widest = 0
    def measure(value):
        nonlocal width, denominators, widest
        if (type(value) is not Fraction or type(value.numerator) is not int or
                type(value.denominator) is not int):
            raise V.VolumeError('plain Fraction metrics required for native mimetic moments')
        numerator, denominator = max(1, value.numerator.bit_length()), value.denominator.bit_length()
        width += numerator+denominator
        denominators += denominator
        widest = max(widest, numerator)
    measure(volume)
    for vector, index in zip(vectors, indexes, strict=True):
        centre = centres[index]
        if len(vector) != 3 or len(centre) != 3:
            raise V.VolumeError('three-dimensional native mimetic metrics required')
        for value in (*vector, *centre):
            measure(value)
    count = len(vectors)
    product = 2*widest+2*denominators+max(1, count.bit_length())+8
    slots = 6*count+17
    native_bytes = (1024+512*count+(width+8*product+7)//8+
                    slots*(OBJECT_BYTES+16*(RECYCLED_LIMBS+2)))
    return width+product, 6*count+1, native_bytes


def _mimetic_moment_fails(vectors, centres, indexes, volume, budget):
    """Nine exact centroid sums in reference order; no native value escapes.

    The caller retains both preceding Python face-distance and area-closure
    checks. Failure leases survive any escaping callback traceback.
    """
    from .integration_spatial_transport import _preserve_workspace

    bits, count, native_bytes = _mimetic_moment_allowance(vectors, centres, indexes, volume)
    with ExitStack() as admitted:
        admitted.enter_context(_work(bits, count, budget))
        admitted.enter_context(budget.reserve(native_bytes, category='exact-native-mimetic-moments'))
        try:
            normals = [tuple(map(_native, vector)) for vector in vectors]
            points = [tuple(map(_native, centres[index])) for index in indexes]
            target = _native(volume)
            failed = bool(any(_total(n[i]*x[j] for n, x in zip(normals, points, strict=True)) !=
                              (target if i == j else 0) for i in range(3) for j in range(3)))
            del normals, points, target
            return failed
        except BaseException as error:
            _failure_owner = _preserve_workspace(error, admitted)
            raise
