"""Source-bound conforming planar geometry for a spatial exterior heat solve.

Planar geometry is a NUMERICAL approximation, not replacement physical support.
The actual support remains cone/shell intersect Cartesian voxel minus the active
grid. Shared radial facets use the continuous Cartesian interpolant of |x|^2;
geometry error is certified against the curved/rotating physical support.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
from itertools import product
import hashlib
import json
import math
import weakref

from . import integration_volume as V
from . import integration_volume_bounds as B
from . import integration_volume_overlap as O
from . import integration_wall_measures as W
from . import integration_collar_geometry as F
from .resources import WorkBudget

# Pose width (c): the stored deviation sum is an outward bound with a short dyadic
# denominator, at most 2**-DEVIATION_STORED_BITS above the exact sum relative.
DEVIATION_STORED_BITS = 64


def _stored_deviation(total, width):
    """Outward short bound of an exact nonnegative sum already checked against width."""
    if type(total) is not Q or type(width) is not Q or not 0 <= total <= width:
        raise V.VolumeError('checked exact deviation sum required')
    if total == 0:
        return total
    e = total.numerator.bit_length()-total.denominator.bit_length()
    if Q(2)**e > total:
        e -= 1
    quantum = Q(2)**(e-DEVIATION_STORED_BITS)
    return min(-((-total)//quantum)*quantum, width)


METHOD = 'continuous-cartesian-quadratic-interpolant-exact-mortar-v1'


def _hash(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _enc(q):
    return V._encoded(Q(q))


def _point(p):
    return list(map(_enc, p))


def resolve_physical_support(record, cell):
    """Expand one exact support declaration from losslessly shared tables.

    This is a record view, not new geometry or a physical admission. The issued
    record hash binds both references and complete table entries.
    """
    if type(record) is ExteriorMesh:
        return record.physical_support(cell)
    tables, refs = record['support_tables'], cell['physical_support']
    if 'differential_support_id' in refs:
        support = tables['differential_supports'][refs['differential_support_id']]
        component = next((r for r in support['components'] if r['logical_cell_id'] == refs['logical_cell_id']), None)
        if component is None:
            raise V.VolumeError('thermal physical support reference has no matching component')
        return json.loads(json.dumps(dict(support=support, component=component), separators=(',', ':')))
    result = dict(voxel=tables['voxels'][refs['voxel_id']])
    if cell['kind'] == 'exterior':
        result.update(radial_layer=tables['radial_layers'][refs['radial_layer_id']],
                      original_cone=tables['cones'][refs['cone_id']],
                      trajectory_id=record['trajectory_id'])
    # Do not return aliases into the caller's record.
    return json.loads(json.dumps(result, separators=(',', ':')))


def _face_normal(ring):
    """Half the closed-ring sum of edge cross products, each evaluated once.

    Every component is the same built-in sum of the same edge terms in ring
    order as three separate passes over the ring would take, so the vector is
    unchanged for every numeric type.
    """
    edges = [O._cross(a, b) for a, b in zip(ring, ring[1:]+ring[:1])]
    return tuple(sum(edge[j] for edge in edges)/2 for j in range(3))


def _face_metrics(ring):
    normal = _face_normal(ring)
    if not any(normal):
        return None
    axis = max(range(3), key=lambda j: abs(normal[j]))
    moment, weight = [Q(0)]*3, Q(0)
    a = ring[0]
    for b, c in zip(ring[1:-1], ring[2:]):
        signed = O._cross(O._minus(b, a), O._minus(c, a))[axis]/2
        weight += signed
        for j in range(3):
            moment[j] += signed*(a[j]+b[j]+c[j])/3
    return normal, tuple(q/weight for q in moment)


def _cell_metrics(poly, arena):
    points = B._points(poly)
    if not points:
        return Q(0), None
    with V._work(tuple(q for p in points for q in p), arena.resource):
        origin, volume, moment = points[0], Q(0), [Q(0)]*3
        for ring in poly:
            a = ring[0]
            for b, c in zip(ring[1:-1], ring[2:]):
                part = O._dot(O._minus(a, origin), O._cross(O._minus(b, origin), O._minus(c, origin)))/6
                if part < 0:
                    raise V.VolumeError('thermal cell has an incorrectly oriented convex face')
                volume += part
                for j in range(3):
                    moment[j] += part*(origin[j]+a[j]+b[j]+c[j])/4
        return volume, None if volume == 0 else tuple(q/volume for q in moment)


def _normalised_face(ring):
    # Only the normal is used here. In exact arithmetic the fan weight of
    # _face_metrics equals the largest normal component of any closed ring, so
    # the centroid it would also compute cannot fail where this normal is nonzero.
    normal = _face_normal(ring)
    if not any(normal):
        return None
    plane = O._plane(normal, O._dot(normal, ring[0]))
    orientation = 1 if next(q for q in plane[:3] if q) > 0 else -1
    plane = tuple(orientation*q for q in plane)
    drop = max(range(3), key=lambda j: abs(plane[j]))
    axes = tuple(j for j in range(3) if j != drop)
    poly = tuple((p[axes[0]], p[axes[1]]) for p in ring)
    signed = sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(poly, poly[1:]+poly[:1]))
    if signed < 0:
        poly = tuple(reversed(poly))
    return plane, orientation, poly


def _lines(poly):
    return tuple((a[1]-b[1], b[0]-a[0], a[0]*b[1]-a[1]*b[0])
                 for a, b in zip(poly, poly[1:]+poly[:1]))


def _area(poly):
    return sum((a[0]*b[1]-a[1]*b[0] for a, b in zip(poly, poly[1:]+poly[:1])), Q(0))/2 if poly else Q(0)


def _intersection(a, b, arena):
    for line in _lines(b):
        arena.work(16+32*len(a))
        a = W._clip2(a, line, arena)
        if not a:
            break
    return a if _area(a) > 0 else ()


def _subtract(poly, holes, arena):
    parts = [poly]
    for hole in holes:
        remaining = []
        for part in parts:
            inside = part
            for line in _lines(hole):
                arena.work(16+32*len(inside))
                outside = W._clip2(inside, tuple(-q for q in line), arena)
                if _area(outside) > 0:
                    remaining.append(outside)
                arena.work(16+32*len(inside))
                inside = W._clip2(inside, line, arena)
                if not inside:
                    break
        parts = remaining
    return parts


def _unmatched_parts(poly, holes, matched_areas, arena):
    """Skip subtraction only after the group's disjointness proof completed.

    Every positive same-side overlap has already been refused by _assemble.
    Thus the opposite intersections of this entry are pairwise disjoint, and
    their exact areas may be added. Equal area leaves no positive-area face;
    all partial matches retain the original polygon subtraction/order. This
    helper alone is not an overlap validator for caller-authored holes.
    """
    arena.work(8*len(poly)+len(matched_areas)+2)
    with V._work(tuple(q for p in poly for q in p)+tuple(matched_areas), arena.resource):
        original = _area(poly)
        covered = sum(matched_areas, Q(0))
        if covered > original:
            raise V.VolumeError('thermal-face matched area exceeds its exact original area')
        if covered == original:
            return ()
    return _subtract(poly, holes, arena)


def _ring3(plane, poly):
    drop = max(range(3), key=lambda j: abs(plane[j]))
    axes = tuple(j for j in range(3) if j != drop)
    points = []
    for u, v in poly:
        p = [Q(0)]*3
        p[axes[0]], p[axes[1]] = u, v
        p[drop] = (plane[3]-plane[axes[0]]*u-plane[axes[1]]*v)/plane[drop]
        points.append(tuple(p))
    points = tuple(sorted(set(points)))
    indices = O._face(points, tuple(range(len(points))), plane[:3])
    if indices is None:
        raise V.VolumeError('positive mortar lost its exact planar ring')
    ring = tuple(points[i] for i in indices)
    start = min(range(len(ring)), key=lambda i: ring[i])
    return ring[start:]+ring[:start]


def _candidate_pairs(entries, arena):
    """Exact projected-box sweep; pairs retain the former (i,j) order.

    Only measure-zero touching boxes are rejected. Cached rational extents are
    search data, never replacement material support. Charge actual examined
    bounds/pairs and clipping work separately, not 64 times every possible
    coplanar pair before the rejection. Returned pair order preserves the exact
    mortar/subtraction decomposition and canonical output identities.
    """
    extents = []
    for _, _, poly in entries:
        arena.work(4*len(poly))
        extents.append(tuple(v for k in range(2) for v in (min(p[k] for p in poly), max(p[k] for p in poly))))
    arena.keep(tuple(v for bounds in extents for v in bounds), len(entries))
    arena.work(len(entries)*max(1, len(entries).bit_length()))
    order = sorted(range(len(entries)), key=lambda i: (extents[i][0], i))
    active, pairs = [], []
    for i in order:
        low, high, bottom, top = extents[i]
        arena.work(len(active))
        active = [j for j in active if extents[j][1] > low]
        for j in active:
            arena.work(2)
            if top <= extents[j][2] or extents[j][3] <= bottom:
                continue
            arena.keep((), 1)
            pairs.append((min(i, j), max(i, j)))
        active.append(i)
    arena.work(len(pairs)*max(1, len(pairs).bit_length()))
    return sorted(pairs)


def _cleared(values):
    """The same exact rationals as integers over one positive denominator."""
    scale = math.lcm(*(q.denominator for q in values))
    return tuple(q.numerator*(scale//q.denominator) for q in values), scale


def _signed_face(face, sign, centre, centre_scale):
    """One signed face of a cell in exact integers, for its metric identities.

    Returns whether area.(centroid-centre) <= 0, and the area vector followed
    by centroid (x) area row by row as numerators over one denominator. Every
    denominator is positive, so clearing them keeps the sense of the
    inequality; the centre is given already cleared, with its denominator.
    The face is one that _assemble issues: its area vector, its centroid and
    the centre have three components each, and its sign is an integer.
    """
    area, area_scale = _cleared(tuple(sign*W._decode(q) for q in face['area_vector_m2']))
    at, at_scale = _cleared(tuple(map(W._decode, face['centroid_m'])))
    moments = [p*q for p in at for q in area]
    nonpositive = ((moments[0]+moments[4]+moments[8])*centre_scale
                   <= (area[0]*centre[0]+area[1]*centre[1]+area[2]*centre[2])*at_scale)
    return nonpositive, ([q*at_scale for q in area]+moments, area_scale*at_scale)


def _closure_fails(terms, volume):
    """True unless sum(area) == 0 and sum(centroid (x) area) == volume*identity.

    The first moment about the cell centre, sum((centroid-centre) (x) area),
    differs from this one by centre (x) sum(area). A closed cell therefore
    satisfies both or neither, and an open one is refused by either form.
    Faces are added pairwise over least common denominators, smallest first,
    so that no long running total is renormalised for every face. The sums
    are exact integers: their order cannot change the decision.
    """
    terms = sorted(terms, key=lambda term: term[1])
    while len(terms) > 1:
        merged = []
        for at in range(0, len(terms)-1, 2):
            (a, da), (b, db) = terms[at], terms[at+1]
            shared = math.gcd(da, db)
            wa, wb = db//shared, da//shared
            merged.append(([a[k]*wa+b[k]*wb for k in range(12)], da*wa))
        terms = merged+terms[2*len(merged):]
    totals, scale = terms[0] if terms else ([0]*12, 1)
    return bool(any(totals[:3]) or any(totals[3+3*i+j]*volume.denominator != (volume.numerator*scale if i == j else 0)
                                       for i in range(3) for j in range(3)))


_MESH_CLOSURE_REFERENCE = _closure_fails


def _admitted_closure_fails(terms, volume, budget):
    """Select one complete cell check; retain the instrumentable Python oracle."""
    if _closure_fails is not _MESH_CLOSURE_REFERENCE:
        return _closure_fails(terms, volume)
    kernel = B._resident()
    if kernel is B:
        return _closure_fails(terms, volume)
    return kernel._mesh_closure_fails(terms, volume, budget)


def _assemble(candidates, arena):
    """Exact face overlay, including one full collar face vs many subfaces."""
    groups, cells, shapes = {}, {}, {}
    for key, poly, metadata in candidates:
        volume, centre = _cell_metrics(poly, arena)
        if volume <= 0:
            raise V.VolumeError('positive convex thermal cells required')
        cells[key] = dict(metadata, cell_id=key, volume_m3=_enc(volume), centroid_m=_point(centre), faces=[])
        shapes[key] = volume, centre
        for ring in poly:
            item = _normalised_face(ring)
            if item is not None:
                plane, sign, flat = item
                groups.setdefault(plane, []).append((key, sign, flat))
    faces = []
    def issue(plane, poly, owners):
        ring = _ring3(plane, poly)
        normal, centre = _face_metrics(ring)
        key = _hash(dict(plane=list(map(_enc, plane)), vertices=[_point(p) for p in ring]))
        if len(owners) == 2 and owners[0][1] == owners[1][1]:
            raise V.VolumeError('matched thermal face has equal rather than opposite incidence')
        kinds = {cells[c]['kind'] for c, _ in owners}
        kind = 'collar-exterior' if kinds == {'collar', 'exterior'} else 'interior' if len(owners) == 2 else 'boundary'
        faces.append(dict(face_id=key, centroid_m=_point(centre), area_vector_m2=_point(normal),
                          owners=[c for c, _ in owners], kind=kind, vertices_m=[_point(p) for p in ring]))
        for c, sign in owners:
            cells[c]['faces'].append([key, sign])
    for plane, entries in sorted(groups.items()):
        opposite = {i: [] for i in range(len(entries))}
        matched_areas = {i: [] for i in range(len(entries))}
        for i, j in _candidate_pairs(entries, arena):
            a, sign_a, poly_a = entries[i]
            b, sign_b, poly_b = entries[j]
            shared = _intersection(poly_a, poly_b, arena)
            if not shared:
                continue
            if sign_a == sign_b or a == b:
                raise V.VolumeError('positive same-side thermal-face overlap reveals overlapping cells')
            arena.work(8*len(shared)+2)
            with V._work(tuple(q for p in shared for q in p), arena.resource):
                area = _area(shared)
            # One rational is shared by the two incident lists. This charge
            # retains its actual width plus both new list references.
            arena.keep((area,), 2)
            matched_areas[i].append(area); matched_areas[j].append(area)
            opposite[i].append(poly_b); opposite[j].append(poly_a)
            issue(plane, shared, ((a, sign_a), (b, sign_b)))
        for i, (key, sign, poly) in enumerate(entries):
            for remaining in _unmatched_parts(poly, opposite[i], matched_areas[i], arena):
                issue(plane, remaining, ((key, sign),))
    by_id = {f['face_id']: f for f in faces}
    if len(by_id) != len(faces):
        raise V.VolumeError('thermal mortar face was issued twice')
    for key, cell in cells.items():
        volume, centre = shapes[key]
        centre, scale = _cleared(centre)
        terms = []
        for face_id, sign in cell['faces']:
            nonpositive, term = _signed_face(by_id[face_id], sign, centre, scale)
            if nonpositive:
                raise V.VolumeError('convex thermal cell has nonpositive normal centre distance')
            terms.append(term)
        if _admitted_closure_fails(terms, volume, arena.resource):
            raise V.VolumeError('exact thermal metric closure or first-moment identity failed')
        cell['faces'].sort()
    return [cells[k] for k in sorted(cells)], sorted(faces, key=lambda f: f['face_id'])


def _qmul(a, b):
    w, x, y, z = a
    v, p, q, r = b
    return w*v-x*p-y*q-z*r, w*p+x*v+y*r-z*q, w*q-x*r+y*v+z*p, w*r+x*q-y*p+z*v


def _segment_quaternion(omega, duration, goal, arena):
    half = tuple(q*duration/2 for q in omega)
    squared, coefficient = O._dot(half, half), sum(map(abs, half))
    cosine = sinc = term_c = term_s = Q(1)
    n = 0
    while True:
        next_c = abs(term_c)*squared/((2*n+1)*(2*n+2))
        next_s = abs(term_s)*squared/((2*n+2)*(2*n+3))
        ratio_c = squared/((2*n+3)*(2*n+4))
        ratio_s = squared/((2*n+4)*(2*n+5))
        if max(ratio_c, ratio_s) < 1:
            error = next_c/(1-ratio_c)+coefficient*next_s/(1-ratio_s)
            if error <= goal:
                return (cosine, *(q*sinc for q in half)), error
        arena.work(64)
        with V._work((*half, squared, term_c, term_s), arena.resource):
            term_c *= -squared/((2*n+1)*(2*n+2))
            term_s *= -squared/((2*n+2)*(2*n+3))
            cosine += term_c; sinc += term_s
        n += 1


# Pose width (b-quat): the product is rounded after every segment with a nonzero
# error to a dyadic quantum <= 2**-POSE_ROUND_GUARD_QUAT of that segment's error.
POSE_ROUND_GUARD_QUAT = 12


def _pose_round_axis(rates):
    """The first nonzero rate if every nonzero rate is exactly parallel to it, else None."""
    moving = [w for w in rates if any(w)]
    if not moving or any(len(w) != 3 or any(type(q) not in (int, Q) for q in w) for w in moving):
        return None
    if any(any(O._cross(w, moving[0])) for w in moving[1:]):
        return None
    return moving[0]


def _pose_round(quaternion, error, delta, axis):
    """The rounded product and its outward error (exact; delta > 0)."""
    quantum = Q(2)**(W._floor_log2(delta)-POSE_ROUND_GUARD_QUAT)
    if axis is None:
        quaternion = W._round_to(quaternion, quantum)
    else:
        # (c1, s1 k)(c2, s2 k) = (c1 c2 - s1 s2 |k|^2, (c1 s2 + c2 s1) k): the
        # product of coaxial factors is (w, s k) exactly. Rounding w and s keeps
        # it so; |ds k|_2 <= q_s/2*|k|_1 <= quantum/2.
        j = max(range(3), key=lambda i: abs(axis[i]))
        s = quaternion[1+j]/axis[j]
        if any(quaternion[1+i] != s*axis[i] for i in range(3)):
            raise V.VolumeError('coaxial pose product left its exact axis')
        step = Q(2)**(W._floor_log2(quantum)-W._ceil_log2(sum(map(abs, axis))))
        s = round(s/step)*step
        quaternion = (round(quaternion[0]/quantum)*quantum, *(s*k for k in axis))
    return quaternion, W._round_up(error+quantum, quantum)


def _representative_pose(segments, operator_goal, arena):
    quaternion, error = (Q(1), Q(0), Q(0), Q(0)), Q(0)
    if not segments:
        return quaternion, error
    goal = operator_goal/(8*len(segments))
    axis = _pose_round_axis([tuple(map(W._decode, record['angular_velocity_rad_s'])) for record in segments])
    for record in segments:
        omega = tuple(map(W._decode, record['angular_velocity_rad_s']))
        duration = W._decode(record['end_time_s'])-W._decode(record['start_time_s'])
        q, delta = _segment_quaternion(omega, duration, goal, arena)
        with V._work((*quaternion, *q, error, delta), arena.resource):
            quaternion = _qmul(q, quaternion)
            error = (1+delta)*error+delta
            if delta:
                quaternion, error = _pose_round(quaternion, error, delta, axis)
    # Normalising an approximate unit quaternion changes its distance by at
    # most another error. Rotation operator distance is at most twice the unit
    # quaternion distance, hence <=4*error. No square root or float pose is used.
    if error >= 1 or 4*error > operator_goal:
        raise V.VolumeError('rational pose failed its derived placement budget')
    return quaternion, 4*error


def _radial_facets(box, inner_radius, outer_radius):
    centre = tuple(box.origin_m[i]+sum(box.basis[i][j]*(box.lower_m[j]+box.upper_m[j])/2
                   for j in range(3)) for i in range(3))
    square = O._dot(centre, centre)
    residual = sum(((b-a)/2)**2 for a, b in zip(box.lower_m, box.upper_m))
    gradient = tuple(2*q for q in centre)
    return ((*gradient, outer_radius**2+square-residual),
            (*(-q for q in gradient), -inner_radius**2-square+residual))


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ExteriorMesh:
    _json: bytes = field(repr=False)
    _compact: object = field(repr=False, compare=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('ExteriorMesh is issued by build_exterior_mesh()')

    @classmethod
    def from_compact(cls, view, *, budget):
        """Admit an exact immutable table view, not a fresh physical certificate."""
        from exterior_mesh_patch import admit_compact_mesh
        return admit_compact_mesh(cls, view, budget=budget)

    def __eq__(self, other):
        if other.__class__ is not self.__class__:
            return NotImplemented
        left, right = getattr(self, '_compact', None), getattr(other, '_compact', None)
        if left is None or right is None:
            # Preserve the legacy byte-representation equality exactly. A
            # compact representation is deliberately a distinct key domain;
            # cross-format scientific identity is the explicit geometry_id.
            return left is right and self._json == other._json
        return left.geometry_id == right.geometry_id

    def __hash__(self):
        compact = getattr(self, '_compact', None)
        if compact is None:
            return hash((self._json,))
        return hash(('compact-exterior-mesh.v1', compact.geometry_id))

    @property
    def is_compact(self):
        return getattr(self, '_compact', None) is not None

    def header(self):
        from exterior_mesh_patch import _view
        return _view(self).header()

    @property
    def cell_count(self):
        from exterior_mesh_patch import _view
        return _view(self).cell_count

    @property
    def face_count(self):
        from exterior_mesh_patch import _view
        return _view(self).face_count

    def cell(self, index):
        from exterior_mesh_patch import _view
        return _view(self).cell(index)

    def face(self, index):
        from exterior_mesh_patch import _view
        return _view(self).face(index)

    def cell_metrics(self, index):
        from exterior_mesh_patch import _view
        return _view(self).cell_metrics(index)

    def face_metrics(self, index):
        from exterior_mesh_patch import _view
        return _view(self).face_metrics(index)

    def support(self, table, identity):
        from exterior_mesh_patch import _view
        return _view(self).support(table, identity)

    def physical_support(self, index):
        from exterior_mesh_patch import physical_support
        return physical_support(self, index)

    def iter_legacy_json(self):
        from exterior_mesh_patch import _view
        return _view(self).iter_legacy_json()

    def legacy_record(self):
        """Explicit costly compatibility export; retain the returned owner."""
        from exterior_mesh_patch import _view
        return _view(self).legacy_record()

    @property
    def geometry_id(self):
        if getattr(self, '_compact', None) is not None:
            from exterior_mesh_patch import _view
            return _view(self).geometry_id
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        if getattr(self, '_compact', None) is not None:
            raise V.VolumeError('compact mesh requires indexed access; explicit legacy_record() returns owned export')
        return json.loads(self._json)

    @classmethod
    def restore(cls, record, *, geometry_id, budget):
        """Restore trusted source/CAS-bound evidence, without re-integration.

        Hash/record admission is not fresh physical certification. The caller
        must bind this record to its saved accepted source and transaction.
        """
        from .integration_regional_inventory import _width
        if type(record) is not dict or type(budget) is not WorkBudget or type(geometry_id) is not str:
            raise V.VolumeError('saved geometry record, identity and shared budget required')
        size = _width(record)
        with budget.reserve(65536+2*size, category='exterior-thermal-mesh-restore'):
            if record.get('schema') != 'atlas.source-bound-exterior-thermal-mesh.v1' or record.get('method') != METHOD:
                raise V.VolumeError('unsupported saved thermal geometry method')
            required = ('cells', 'faces', 'support_tables', 'funding_id', 'source', 'support_id',
                        'trajectory_id', 'time_s', 'grid_id', 'grid_lines', 'endpoint', 'trajectory_segments')
            if any(k not in record for k in required) or _hash(record) != geometry_id:
                raise V.VolumeError('saved thermal geometry identity or record contract changed')
            if record['endpoint'] not in ('start', 'end') or _hash(record['trajectory_segments']) != record['trajectory_id']:
                raise V.VolumeError('saved thermal trajectory differs')
            encoded = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            lease = budget.reserve(8192+4*len(encoded), category='exterior-thermal-mesh-retained')
            lease.__enter__()
            try:
                result = object.__new__(cls)
                object.__setattr__(result, '_json', encoded); object.__setattr__(result, '_resource', budget)
                weakref.finalize(result, lease.__exit__, None, None, None)
                return result
            except BaseException:
                lease.__exit__(None, None, None)
                raise


def build_exterior_mesh(funding, sphere, wall_measures, *, grid_lines,
                        max_geometry_volume_error_m3, max_leaves, budget, endpoint='end'):
    """Build collar plus actual-source exterior convex thermal cells.

    Caller supplies the bounded conforming grid and physical volume-error
    criterion BEFORE execution. No source stock is assigned or normalised.
    Physical positive/uncertain support without a positive surrogate refuses;
    it is never dropped as a small cell or disguised by the global error sum.
    """
    from . import integration_support as U
    if type(funding) is not F.FullCellFunding or type(wall_measures) is not W.WallMeasures:
        raise V.VolumeError('issued source funding and current physical wall/pose evidence required')
    if endpoint not in ('start', 'end'):
        raise V.VolumeError('physical start or end endpoint required')
    if type(budget) is not WorkBudget or funding._resource is not budget or wall_measures._resource is not budget:
        raise V.VolumeError('one shared explicit source/geometry WorkBudget required')
    if type(grid_lines) is not tuple or len(grid_lines) != 3 or any(type(q) is not tuple or len(q) < 2 for q in grid_lines):
        raise V.VolumeError('three explicit finite coordinate-line tuples required')
    width = W._q(max_geometry_volume_error_m3)
    if width <= 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive predeclared geometric error and finite subdivision budget required')
    record, motion = funding.descriptor(), wall_measures.descriptor()
    if motion['funding_id'] != funding.funding_id or record['source']['sphere_state_id'] != sphere.state_id:
        raise V.VolumeError('thermal mesh source/funding/pose binding differs')
    with budget.reserve(131072+2*funding._snapshot.nbytes+2*len(wall_measures._json), category='thermal-mesh-source'), B._Arena(budget) as arena:
        with V._work(tuple(q for axis in grid_lines for q in axis), budget) as values:
            lines, offset = [], 0
            for axis in grid_lines:
                line = values[offset:offset+len(axis)]; offset += len(axis)
                if any(a >= b for a, b in zip(line, line[1:])):
                    raise V.VolumeError('thermal grid lines must be strictly increasing')
                lines.append(line)
            lines = tuple(lines)
        collar_cells = tuple(V.CartesianCell.from_record(r, budget=budget) for r in record['cell_geometries'])
        first = collar_cells[0]
        origin, basis = first.origin_m, first.basis
        if any(c.origin_m != origin or c.basis != basis for c in collar_cells):
            raise V.VolumeError('one actual exact Cartesian embedding required')
        radius = Q(sphere.network.sphere.radius_m)
        translation = tuple(sum(basis[k][j]*origin[k] for k in range(3)) for j in range(3))
        if any(line[0] > -radius-t or line[-1] < radius-t for line, t in zip(lines, translation)):
            raise V.VolumeError('declared thermal grid does not contain the complete funded radial source')
        for axis in range(3):
            required = {q for c in collar_cells for q in (c.lower_m[axis], c.upper_m[axis])}
            if not required.issubset(lines[axis]):
                raise V.VolumeError('grid must retain every actual active-cell face coordinate')
        support = U.required(sphere.material)
        keys = tuple((r['patch_id'], r['sublayer']) for r in record['exterior_remainder'])
        patches = {p.patch_id: p for p in support.patches if p.patch_id in {k[0] for k in keys}}
        charts = {}
        for key, patch in patches.items():
            try:
                charts[key] = (V.convex_cone_union(patch.cells, budget=budget),)
            except V.VolumeError:
                charts[key] = patch.cells
        geometry = {}
        for r in record['exterior_remainder']:
            g = r['radial_layer']
            geometry[(r['patch_id'], r['sublayer'])] = V.RadialLayer(*(W._decode(g[k]) for k in
                ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
        levels = sorted({q for layer in geometry.values() for q in (layer.bottom_radius_m, layer.top_radius_m)})
        bands = tuple(zip(levels, levels[1:]))
        voxel_count = math.prod(len(line)-1 for line in lines)
        count_bound = voxel_count*sum(map(len, charts.values()))*len(bands)
        arena.keep((width,), 8*count_bound)
        arena.work(128*count_bound)
        # A normal-direction error δ can only change membership in a spherical
        # strip of solid angle <=4*pi*δ. With pi<4, the union of N changed
        # halfspaces differs by at most (16/3)*N*R^3*δ. Allocate at most half
        # the caller's volume budget to pose placement, before any experiment.
        nplanes = sum(len(c) for cones in charts.values() for c in cones)
        pose_goal = min(Q(1, 2), 3*width/(32*nplanes*radius**3))
        history = motion['trajectory']['segments']
        segments = history if endpoint == 'end' else history[:-1]
        support_id = motion[endpoint+'_support_id']
        trajectory_id = motion['trajectory_id' if endpoint == 'end' else 'prior_trajectory_id']
        quaternion, pose_error = _representative_pose(segments, pose_goal, arena)
        rotation = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated(quaternion, budget=budget).basis
        posed = {p: tuple(tuple(tuple(sum(rotation[i][j]*ray[j] for j in range(3)) for i in range(3))
                                  for ray in cone) for cone in cones) for p, cones in charts.items()}
        last = history[-1]
        prior = tuple((tuple(map(W._decode, r['angular_velocity_rad_s'])),
                       W._decode(r['end_time_s'])-W._decode(r['start_time_s'])) for r in history[:-1])
        omega = tuple(map(W._decode, last['angular_velocity_rad_s']))
        time = W._decode(last['end_time_s'])-W._decode(last['start_time_s']) if endpoint == 'end' else Q(0)
        integration_width = width/(2*max(1, count_bound))
        active_lower = tuple(min(c.lower_m[j] for c in collar_cells) for j in range(3))
        active_upper = tuple(max(c.upper_m[j] for c in collar_cells) for j in range(3))
        candidates, total_error, box_by_cell, radial_by_cell = [], Q(0), {}, {}
        support_tables = dict(voxels={}, radial_layers={}, cones={})
        def support_refs(box, layer=None, cone=None):
            support_tables['voxels'].setdefault(box.cell_id, box.record())
            refs = dict(voxel_id=box.cell_id)
            if layer is not None:
                layer_record, cone_record = layer.record(), [_point(p) for p in cone]
                layer_id, cone_id = _hash(layer_record), _hash(cone_record)
                support_tables['radial_layers'].setdefault(layer_id, layer_record)
                support_tables['cones'].setdefault(cone_id, cone_record)
                refs.update(radial_layer_id=layer_id, cone_id=cone_id)
            return refs
        grid_id = _hash(dict(lines=[list(map(_enc, axis)) for axis in lines], origin=_point(origin), basis=[_point(r) for r in basis]))
        for flat, cell in enumerate(collar_cells):
            at = (flat//(record['cells'][1]*record['cells'][2]),
                  flat//record['cells'][2] % record['cells'][1], flat % record['cells'][2])
            key = _hash(dict(kind='collar', funding_id=funding.funding_id, cell_id=cell.cell_id))
            box_by_cell[key] = cell
            candidates.append((key, B._box(cell), dict(kind='collar', index=list(at), logical_cell_id=key,
                physical_volume_bounds_m3=[_enc(cell.volume_m3)]*2, geometry_volume_max_deviation_m3=_enc(0),
                physical_cell_id=cell.cell_id, physical_support=support_refs(cell))))
        for at in product(*(range(len(axis)-1) for axis in lines)):
            lower = tuple(lines[j][at[j]] for j in range(3)); upper = tuple(lines[j][at[j]+1] for j in range(3))
            if all(active_lower[j] <= lower[j] and upper[j] <= active_upper[j] for j in range(3)):
                continue
            box = V.CartesianCell(lower, upper, origin, basis, budget=budget)
            radial_min, radial_max = box._radial_bounds()
            if radial_min >= radius**2:
                continue
            for source_key, layer in geometry.items():
                for band_index, (rb, rt) in enumerate(bands):
                    if rb < layer.bottom_radius_m or rt > layer.top_radius_m or radial_min >= rt**2 or radial_max <= rb**2:
                        continue
                    physical_layer = V.RadialLayer(radius, radius-rt, radius-rb, budget=budget)
                    for chart_index, (actual_cone, placed_cone) in enumerate(zip(charts[source_key[0]], posed[source_key[0]])):
                        poly = B._box(box)
                        for plane in F._cone_planes(placed_cone):
                            poly = B._clip(poly, plane, arena)
                            if not poly:
                                break
                        radial_facets = _radial_facets(box, rb, rt)
                        for plane in radial_facets:
                            poly = B._clip(poly, plane, arena)
                        volume = B._volume(poly, arena)
                        lo, hi = W._endpoint_volume(physical_layer, (actual_cone,), box, omega, time,
                            integration_width, max_leaves, budget, prior, positive_witness=True)
                        if volume == 0:
                            if hi > 0:
                                raise V.VolumeError('positive or unresolved physical sliver has no thermal surrogate; refine the declared grid')
                            continue
                        if hi == 0:
                            raise V.VolumeError('thermal surrogate has no physical support; refine grid/pose placement')
                        if lo == 0:
                            raise V.VolumeError('positive thermal cell lacks a certified positive physical subset within the declared leaf/work cap; refine grid or integration')
                        error = max(abs(volume-lo), abs(volume-hi))
                        total_error += error
                        logical = _hash(dict(source_key=list(source_key), grid_id=grid_id, voxel_index=list(at),
                            radial_band=band_index, chart=chart_index))
                        key = _hash(dict(logical_cell_id=logical, support_id=support_id))
                        box_by_cell[key], radial_by_cell[key] = box, radial_facets
                        candidates.append((key, poly, dict(kind='exterior', source_key=list(source_key), logical_cell_id=logical,
                            voxel_index=list(at), radial_band=band_index, chart=chart_index,
                            physical_volume_bounds_m3=list(map(_enc, (lo, hi))), geometry_volume_max_deviation_m3=_enc(error),
                            physical_support=support_refs(box, physical_layer, actual_cone))))
        if total_error > width:
            raise V.VolumeError('declared spatial grid exceeds the predeclared physical geometry volume-error budget')
        total_error = _stored_deviation(total_error, width)
        cells, faces = _assemble(candidates, arena)
        # All collar faces must have a real neighbour. No missing exterior
        # support can become an accidental insulating/free boundary.
        by_cell = {c['cell_id']: c for c in cells}
        for face in faces:
            points = tuple(tuple(map(W._decode, p)) for p in face['vertices_m'])
            cartesian = []
            for key in face['owners']:
                box = box_by_cell[key]
                local = tuple(tuple(sum(box.basis[i][j]*(p[i]-box.origin_m[i]) for i in range(3))
                                    for j in range(3)) for p in points)
                for axis in range(3):
                    for end, coordinate in enumerate((box.lower_m[axis], box.upper_m[axis])):
                        if all(p[axis] == coordinate for p in local):
                            cartesian.append(dict(cell_id=key, physical_voxel_id=box.cell_id, axis=axis, end=end,
                                                  local_coordinate_m=_enc(coordinate)))
            if cartesian:
                face['geometry_kind'] = 'cartesian'
                face['cartesian_support'] = cartesian
                face['relative_advection'] = 'actual certified Cartesian face-time material measure'
            elif any(all(O._dot(plane[:3], p) == plane[3] for p in points)
                     for key in face['owners'] for plane in radial_by_cell.get(key, ())):
                face['geometry_kind'] = 'radial-facet'
                face['relative_advection'] = 'zero on the actual physical spherical radial interface'
            else:
                face['geometry_kind'] = 'material-cone'
                face['relative_advection'] = 'zero relative to the common rigid material-cone motion'
        if any(len(f['owners']) == 1 and by_cell[f['owners'][0]]['kind'] == 'collar' for f in faces):
            raise V.VolumeError('thermal exterior does not cover every actual active-grid boundary face')
        result_record = dict(schema='atlas.source-bound-exterior-thermal-mesh.v1', method=METHOD,
            funding_id=funding.funding_id, source=record['source'], support_id=support_id,
            trajectory_id=trajectory_id, trajectory_segments=segments, endpoint=endpoint,
            wall_measure_id=wall_measures.measure_id, time_s=motion[endpoint+'_time_s'], grid_id=grid_id,
            grid_lines=[list(map(_enc, axis)) for axis in lines], cells=cells, faces=faces,
            support_tables=support_tables,
            representative_quaternion=list(map(_enc, quaternion)), pose_operator_error_bound=_enc(pose_error),
            geometry_volume_max_deviation_m3=_enc(total_error), max_geometry_volume_error_m3=_enc(width),
            radial_rule='continuous piecewise-affine Cartesian interpolant of squared radius',
            endpoint_lower_rule='maximum of outward-rounded lower sum and exact true-support inner-subset witness; same leaf/work cap',
            advection_rule='actual cone/radial shell; exactly zero physical relative radial/material-boundary flux, never omega dot faceted normal',
            scope='certified numerical thermal geometry only; no capacity allocation, conduction solve or stock remap')
        encoded = json.dumps(result_record, sort_keys=True, separators=(',', ':')).encode()
        lease = budget.reserve(8192+4*len(encoded), category='exterior-thermal-mesh-retained')
        lease.__enter__()
        try:
            result = object.__new__(ExteriorMesh)
            object.__setattr__(result, '_json', encoded); object.__setattr__(result, '_resource', budget)
            weakref.finalize(result, lease.__exit__, None, None, None)
            return result
        except BaseException:
            lease.__exit__(None, None, None)
            raise


def _build_exterior_mesh_record(funding, sphere, wall_measures, *, grid_lines,
                        max_geometry_volume_error_m3, max_leaves, budget, endpoint='end'):
    """Build collar plus actual-source exterior convex thermal cells.

    Caller supplies the bounded conforming grid and physical volume-error
    criterion BEFORE execution. No source stock is assigned or normalised.
    Physical positive/uncertain support without a positive surrogate refuses;
    it is never dropped as a small cell or disguised by the global error sum.
    """
    from . import integration_support as U
    if type(funding) is not F.FullCellFunding or type(wall_measures) is not W.WallMeasures:
        raise V.VolumeError('issued source funding and current physical wall/pose evidence required')
    if endpoint not in ('start', 'end'):
        raise V.VolumeError('physical start or end endpoint required')
    if type(budget) is not WorkBudget or funding._resource is not budget or wall_measures._resource is not budget:
        raise V.VolumeError('one shared explicit source/geometry WorkBudget required')
    if type(grid_lines) is not tuple or len(grid_lines) != 3 or any(type(q) is not tuple or len(q) < 2 for q in grid_lines):
        raise V.VolumeError('three explicit finite coordinate-line tuples required')
    width = W._q(max_geometry_volume_error_m3)
    if width <= 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive predeclared geometric error and finite subdivision budget required')
    record, motion = funding.descriptor(), wall_measures.descriptor()
    if motion['funding_id'] != funding.funding_id or record['source']['sphere_state_id'] != sphere.state_id:
        raise V.VolumeError('thermal mesh source/funding/pose binding differs')
    with budget.reserve(131072+2*funding._snapshot.nbytes+2*len(wall_measures._json), category='thermal-mesh-source'), B._Arena(budget) as arena:
        with V._work(tuple(q for axis in grid_lines for q in axis), budget) as values:
            lines, offset = [], 0
            for axis in grid_lines:
                line = values[offset:offset+len(axis)]; offset += len(axis)
                if any(a >= b for a, b in zip(line, line[1:])):
                    raise V.VolumeError('thermal grid lines must be strictly increasing')
                lines.append(line)
            lines = tuple(lines)
        collar_cells = tuple(V.CartesianCell.from_record(r, budget=budget) for r in record['cell_geometries'])
        first = collar_cells[0]
        origin, basis = first.origin_m, first.basis
        if any(c.origin_m != origin or c.basis != basis for c in collar_cells):
            raise V.VolumeError('one actual exact Cartesian embedding required')
        radius = Q(sphere.network.sphere.radius_m)
        translation = tuple(sum(basis[k][j]*origin[k] for k in range(3)) for j in range(3))
        if any(line[0] > -radius-t or line[-1] < radius-t for line, t in zip(lines, translation)):
            raise V.VolumeError('declared thermal grid does not contain the complete funded radial source')
        for axis in range(3):
            required = {q for c in collar_cells for q in (c.lower_m[axis], c.upper_m[axis])}
            if not required.issubset(lines[axis]):
                raise V.VolumeError('grid must retain every actual active-cell face coordinate')
        support = U.required(sphere.material)
        keys = tuple((r['patch_id'], r['sublayer']) for r in record['exterior_remainder'])
        patches = {p.patch_id: p for p in support.patches if p.patch_id in {k[0] for k in keys}}
        charts = {}
        for key, patch in patches.items():
            try:
                charts[key] = (V.convex_cone_union(patch.cells, budget=budget),)
            except V.VolumeError:
                charts[key] = patch.cells
        geometry = {}
        for r in record['exterior_remainder']:
            g = r['radial_layer']
            geometry[(r['patch_id'], r['sublayer'])] = V.RadialLayer(*(W._decode(g[k]) for k in
                ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
        levels = sorted({q for layer in geometry.values() for q in (layer.bottom_radius_m, layer.top_radius_m)})
        bands = tuple(zip(levels, levels[1:]))
        voxel_count = math.prod(len(line)-1 for line in lines)
        count_bound = voxel_count*sum(map(len, charts.values()))*len(bands)
        arena.keep((width,), 8*count_bound)
        arena.work(128*count_bound)
        # A normal-direction error δ can only change membership in a spherical
        # strip of solid angle <=4*pi*δ. With pi<4, the union of N changed
        # halfspaces differs by at most (16/3)*N*R^3*δ. Allocate at most half
        # the caller's volume budget to pose placement, before any experiment.
        nplanes = sum(len(c) for cones in charts.values() for c in cones)
        pose_goal = min(Q(1, 2), 3*width/(32*nplanes*radius**3))
        history = motion['trajectory']['segments']
        segments = history if endpoint == 'end' else history[:-1]
        support_id = motion[endpoint+'_support_id']
        trajectory_id = motion['trajectory_id' if endpoint == 'end' else 'prior_trajectory_id']
        quaternion, pose_error = _representative_pose(segments, pose_goal, arena)
        rotation = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated(quaternion, budget=budget).basis
        posed = {p: tuple(tuple(tuple(sum(rotation[i][j]*ray[j] for j in range(3)) for i in range(3))
                                  for ray in cone) for cone in cones) for p, cones in charts.items()}
        last = history[-1]
        prior = tuple((tuple(map(W._decode, r['angular_velocity_rad_s'])),
                       W._decode(r['end_time_s'])-W._decode(r['start_time_s'])) for r in history[:-1])
        omega = tuple(map(W._decode, last['angular_velocity_rad_s']))
        time = W._decode(last['end_time_s'])-W._decode(last['start_time_s']) if endpoint == 'end' else Q(0)
        integration_width = width/(2*max(1, count_bound))
        active_lower = tuple(min(c.lower_m[j] for c in collar_cells) for j in range(3))
        active_upper = tuple(max(c.upper_m[j] for c in collar_cells) for j in range(3))
        candidates, total_error, box_by_cell, radial_by_cell = [], Q(0), {}, {}
        support_tables = dict(voxels={}, radial_layers={}, cones={})
        def support_refs(box, layer=None, cone=None):
            support_tables['voxels'].setdefault(box.cell_id, box.record())
            refs = dict(voxel_id=box.cell_id)
            if layer is not None:
                layer_record, cone_record = layer.record(), [_point(p) for p in cone]
                layer_id, cone_id = _hash(layer_record), _hash(cone_record)
                support_tables['radial_layers'].setdefault(layer_id, layer_record)
                support_tables['cones'].setdefault(cone_id, cone_record)
                refs.update(radial_layer_id=layer_id, cone_id=cone_id)
            return refs
        grid_id = _hash(dict(lines=[list(map(_enc, axis)) for axis in lines], origin=_point(origin), basis=[_point(r) for r in basis]))
        for flat, cell in enumerate(collar_cells):
            at = (flat//(record['cells'][1]*record['cells'][2]),
                  flat//record['cells'][2] % record['cells'][1], flat % record['cells'][2])
            key = _hash(dict(kind='collar', funding_id=funding.funding_id, cell_id=cell.cell_id))
            box_by_cell[key] = cell
            candidates.append((key, B._box(cell), dict(kind='collar', index=list(at), logical_cell_id=key,
                physical_volume_bounds_m3=[_enc(cell.volume_m3)]*2, geometry_volume_max_deviation_m3=_enc(0),
                physical_cell_id=cell.cell_id, physical_support=support_refs(cell))))
        for at in product(*(range(len(axis)-1) for axis in lines)):
            lower = tuple(lines[j][at[j]] for j in range(3)); upper = tuple(lines[j][at[j]+1] for j in range(3))
            if all(active_lower[j] <= lower[j] and upper[j] <= active_upper[j] for j in range(3)):
                continue
            box = V.CartesianCell(lower, upper, origin, basis, budget=budget)
            radial_min, radial_max = box._radial_bounds()
            if radial_min >= radius**2:
                continue
            for source_key, layer in geometry.items():
                for band_index, (rb, rt) in enumerate(bands):
                    if rb < layer.bottom_radius_m or rt > layer.top_radius_m or radial_min >= rt**2 or radial_max <= rb**2:
                        continue
                    physical_layer = V.RadialLayer(radius, radius-rt, radius-rb, budget=budget)
                    for chart_index, (actual_cone, placed_cone) in enumerate(zip(charts[source_key[0]], posed[source_key[0]])):
                        poly = B._box(box)
                        for plane in F._cone_planes(placed_cone):
                            poly = B._clip(poly, plane, arena)
                            if not poly:
                                break
                        radial_facets = _radial_facets(box, rb, rt)
                        for plane in radial_facets:
                            poly = B._clip(poly, plane, arena)
                        volume = B._volume(poly, arena)
                        lo, hi = W._endpoint_volume(physical_layer, (actual_cone,), box, omega, time,
                            integration_width, max_leaves, budget, prior, positive_witness=True)
                        if volume == 0:
                            if hi > 0:
                                raise V.VolumeError('positive or unresolved physical sliver has no thermal surrogate; refine the declared grid')
                            continue
                        if hi == 0:
                            raise V.VolumeError('thermal surrogate has no physical support; refine grid/pose placement')
                        if lo == 0:
                            raise V.VolumeError('positive thermal cell lacks a certified positive physical subset within the declared leaf/work cap; refine grid or integration')
                        error = max(abs(volume-lo), abs(volume-hi))
                        total_error += error
                        logical = _hash(dict(source_key=list(source_key), grid_id=grid_id, voxel_index=list(at),
                            radial_band=band_index, chart=chart_index))
                        key = _hash(dict(logical_cell_id=logical, support_id=support_id))
                        box_by_cell[key], radial_by_cell[key] = box, radial_facets
                        candidates.append((key, poly, dict(kind='exterior', source_key=list(source_key), logical_cell_id=logical,
                            voxel_index=list(at), radial_band=band_index, chart=chart_index,
                            physical_volume_bounds_m3=list(map(_enc, (lo, hi))), geometry_volume_max_deviation_m3=_enc(error),
                            physical_support=support_refs(box, physical_layer, actual_cone))))
        if total_error > width:
            raise V.VolumeError('declared spatial grid exceeds the predeclared physical geometry volume-error budget')
        total_error = _stored_deviation(total_error, width)
        import live_mesh_patch as _LIVE_MESH
        if _LIVE_MESH.EARLY_RELEASE:
            # Charts, poses, layers and collar cells end with the candidate loop.
            del charts, posed, geometry, bands, collar_cells, prior, omega, time
        cells, faces = _assemble(_LIVE_MESH.drain(candidates) if _LIVE_MESH.EARLY_RELEASE else candidates, arena)
        del candidates
        # All collar faces must have a real neighbour. No missing exterior
        # support can become an accidental insulating/free boundary.
        by_cell = {c['cell_id']: c for c in cells}
        for face in faces:
            points = tuple(tuple(map(W._decode, p)) for p in face['vertices_m'])
            cartesian = []
            for key in face['owners']:
                box = box_by_cell[key]
                local = tuple(tuple(sum(box.basis[i][j]*(p[i]-box.origin_m[i]) for i in range(3))
                                    for j in range(3)) for p in points)
                for axis in range(3):
                    for end, coordinate in enumerate((box.lower_m[axis], box.upper_m[axis])):
                        if all(p[axis] == coordinate for p in local):
                            cartesian.append(dict(cell_id=key, physical_voxel_id=box.cell_id, axis=axis, end=end,
                                                  local_coordinate_m=_enc(coordinate)))
            if cartesian:
                face['geometry_kind'] = 'cartesian'
                face['cartesian_support'] = cartesian
                face['relative_advection'] = 'actual certified Cartesian face-time material measure'
            elif any(all(O._dot(plane[:3], p) == plane[3] for p in points)
                     for key in face['owners'] for plane in radial_by_cell.get(key, ())):
                face['geometry_kind'] = 'radial-facet'
                face['relative_advection'] = 'zero on the actual physical spherical radial interface'
            else:
                face['geometry_kind'] = 'material-cone'
                face['relative_advection'] = 'zero relative to the common rigid material-cone motion'
        if any(len(f['owners']) == 1 and by_cell[f['owners'][0]]['kind'] == 'collar' for f in faces):
            raise V.VolumeError('thermal exterior does not cover every actual active-grid boundary face')
        if _LIVE_MESH.EARLY_RELEASE:
            del box_by_cell, radial_by_cell, by_cell
        result_record = dict(schema='atlas.source-bound-exterior-thermal-mesh.v1', method=METHOD,
            funding_id=funding.funding_id, source=record['source'], support_id=support_id,
            trajectory_id=trajectory_id, trajectory_segments=segments, endpoint=endpoint,
            wall_measure_id=wall_measures.measure_id, time_s=motion[endpoint+'_time_s'], grid_id=grid_id,
            grid_lines=[list(map(_enc, axis)) for axis in lines], cells=cells, faces=faces,
            support_tables=support_tables,
            representative_quaternion=list(map(_enc, quaternion)), pose_operator_error_bound=_enc(pose_error),
            geometry_volume_max_deviation_m3=_enc(total_error), max_geometry_volume_error_m3=_enc(width),
            radial_rule='continuous piecewise-affine Cartesian interpolant of squared radius',
            endpoint_lower_rule='maximum of outward-rounded lower sum and exact true-support inner-subset witness; same leaf/work cap',
            advection_rule='actual cone/radial shell; exactly zero physical relative radial/material-boundary flux, never omega dot faceted normal',
            scope='certified numerical thermal geometry only; no capacity allocation, conduction solve or stock remap')
        from live_mesh_patch import own_record
        return own_record(result_record, budget)


_build_exterior_mesh_native = build_exterior_mesh

def build_exterior_mesh(funding, sphere, wall_measures, *, grid_lines,
                        max_geometry_volume_error_m3, max_leaves, budget, endpoint='end', compact_context=None):
    if compact_context is None:
        return _build_exterior_mesh_native(funding, sphere, wall_measures, grid_lines=grid_lines,
            max_geometry_volume_error_m3=max_geometry_volume_error_m3, max_leaves=max_leaves,
            budget=budget, endpoint=endpoint)
    from live_mesh_patch import build
    return build(_build_exterior_mesh_record, (funding, sphere, wall_measures), dict(grid_lines=grid_lines,
        max_geometry_volume_error_m3=max_geometry_volume_error_m3, max_leaves=max_leaves,
        budget=budget, endpoint=endpoint), compact_context)
