"""Current common-trajectory pressure from positioned finite-volume material.

Physical interfaces use the original named radial wall and the retained exact
trajectory, enclosed by an issued rational pose. Thermal surrogate facets and
whole-patch mean temperatures never enter the wall/pressure-ray integrals.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import json
import math
import weakref

import numpy as np

from . import integration_pressure_coupling as C
from . import integration_volume as V, integration_volume_overlap as O
from . import integration_current_force_pose as F
from . import integration_wall_measures as W
from .regional_execution import RegionalMechanicalSnapshot


def _rotate_bounds(bounds, pose):
    rotation, error = pose.rotation(), pose._error
    norm = sum(max(abs(a), abs(b)) for a, b in bounds)
    result = []
    for row in rotation:
        value = (Q(0), Q(0))
        for q, pair in zip(row, bounds):
            value = C._add(value, C._scale(pair, q))
        result.append((value[0]-error*norm, value[1]+error*norm))
    return tuple(result)


def _common_axis(rotation, steps):
    """Exact k that every nonzero step vector is parallel to and that Q and Q^T fix, or None."""
    vectors = [vector for vector in steps if any(vector)]
    if not vectors or any(any(O._cross(vector, vectors[0])) for vector in vectors[1:]):
        return None
    axis = vectors[0]
    if any(O._dot(row, axis) != q or O._dot(column, axis) != q
           for row, column, q in zip(rotation, zip(*rotation), axis)):
        return None
    return axis


def _pose_axis(pose, budget):
    """Exact invariant axis k of an uncertain posed boundary, or None.

    A boundary view carries in _history the exact angular velocity of every
    step of its true rotation. Like _error, that is a statement about the TRUE
    pose which this kernel cannot prove and must be given by the pose's issuer.
    Everything drawn from it is proved here on every call, in exact arithmetic,
    and no stored conclusion is read: if every nonzero step is parallel to one
    k, the true pose turns about k, so Qtrue^T k = k. With Q^T k = k as well,
    k.(Qtrue x - Q x) = 0 for every x: the pose error moves no point along k.
    Q k = k keeps a plane normal to k where the representative puts it. A pose
    object without a history of three-component steps, and an exact pose, has
    no axis.
    """
    steps = getattr(pose, '_history', None)
    if not steps or pose._error == 0 or any(len(vector) != 3 for vector in steps):
        return None
    with V._work((*(q for row in pose.rotation() for q in row), *(q for vector in steps for q in vector)),
                 budget) as values:
        return _common_axis(tuple(values[i:i+3] for i in (0, 3, 6)),
                            [values[i:i+3] for i in range(9, len(values), 3)])


def _pose_norm(vector, axis):
    """Rational bound of |vector.(Qtrue x - Q x)|/(delta |x|).

    The L1 norm bounds the Euclidean one. With a certified axis the difference
    is orthogonal to it, so only the part of the vector across the axis acts;
    that part is exactly zero for a vector along the axis.
    """
    norm = sum(map(abs, vector))
    if axis is None:
        return norm
    along = O._dot(vector, axis)/O._dot(axis, axis)
    return min(norm, sum(abs(v-along*k) for v, k in zip(vector, axis)))


def _constraint_numbers(constraint):
    """Exact issuer inputs charged before the plane-path proof's arithmetic."""
    kind = constraint['kind']
    if kind == 'snapshot-rotated':
        nested = _constraint_numbers(constraint['constraint'])
        if nested is None:
            return None
        return (*nested, W._decode(constraint['snapshot_offset_s']),
                *map(W._decode, constraint['angular_velocity_rad_s']))
    if kind == 'fixed-plane':
        return (*map(W._decode, constraint['normal']), W._decode(constraint['offset']))
    if kind == 'rotated-normal':
        return (*map(W._decode, constraint['normal']),
                *map(W._decode, constraint['angular_velocity_rad_s']))
    if kind == 'moving-ray-edge':
        values = []
        for ray in constraint['rays']:
            values.extend(map(W._decode, ray['direction']))
            values.extend(map(W._decode, ray['angular_velocity_rad_s']))
            for step in ray.get('prior_rotations', ()):
                values.extend(map(W._decode, step['angular_velocity_rad_s']))
                values.append(W._decode(step['duration_s']))
        return tuple(values)
    return None


def _rotation_path(steps, normal=None):
    """Ordered exact rotation vectors; combine only adjacent commuting steps.

    Initial rotations about the original normal fix that plane. Apart from
    those, no step is dropped, reordered, or replaced by a fitted net angle.
    """
    result = []
    for vector in steps:
        if not any(vector):
            continue
        if not result and normal is not None and not any(O._cross(normal, vector)):
            continue
        if result and not any(O._cross(result[-1], vector)):
            vector = tuple(a+b for a, b in zip(result.pop(), vector))
        if any(vector):
            result.append(vector)
    return tuple(result)


def _constraint_plane_path(constraint, time):
    """Original homogeneous plane and its complete exact ordered rotations.

    Snapshot wrappers evaluate their child at its recorded offset, then apply
    their own rotation for this support's elapsed endpoint time. A genuinely
    deforming edge has no such path and retains the numerical enclosure.
    """
    from . import integration_differential_geometry as G
    kind = constraint['kind']
    if kind == 'snapshot-rotated':
        nested = _constraint_plane_path(constraint['constraint'], W._decode(constraint['snapshot_offset_s']))
        if nested is None:
            return None
        normal, steps = nested
        return normal, (*steps, tuple(time*q for q in G._load_vec(constraint['angular_velocity_rad_s'])))
    if kind == 'moving-ray-edge':
        if len(constraint['rays']) != 2:
            return None
        directions, paths = [], []
        for ray in constraint['rays']:
            direction = G._load_vec(ray['direction'])
            history = (*G._history(ray.get('prior_rotations', ())),
                       (G._load_vec(ray['angular_velocity_rad_s']), time))
            if len(direction) != 3 or any(len(vector) != 3 for vector, _ in history):
                return None
            directions.append(direction)
            paths.append(_rotation_path(tuple(tuple(q*dt for q in vector) for vector, dt in history)))
        if paths[0] == paths[1]:
            return O._cross(*directions), paths[0]
        # The geometry issuer already proves the additional coaxial case:
        # a fixed axial ray and one rotating ray form a rigid moving plane.
    path = G._rigid_plane_path(constraint)
    if path is None:
        return None
    normal, theta, velocity = path
    if any(len(vector) != 3 for vector in (normal, theta, velocity)):
        return None
    return normal, (theta, tuple(time*q for q in velocity))


def _face_on_wall(constraint, time, first, second, pose, budget):
    """Prove one issuer-backed closed face contains this true radial wall.

    Only a nondegenerate homogeneous original plane and the entire retained
    rotation history can prove contact. Parallel original normals may have
    either orientation: all wall points satisfy either closed inequality at
    equality. Representative proximity, normal error and tolerances play no
    part. A missing history is unknown, including when its representative is
    identity. The proof is local to this wall; it grants no general removal.
    """
    history = getattr(pose, '_plane_history', None)
    if history is None or any(len(vector) != 3 for vector, _ in history):
        return False
    numbers = _constraint_numbers(constraint)
    if numbers is None:
        return False
    values = (*first, *second, time, *numbers,
              *(q for vector, dt in history for q in (*vector, dt)))
    with V._work(values, budget):
        wall = O._cross(first, second)
        if not any(wall):
            return False
        path = _constraint_plane_path(constraint, time)
        if path is None:
            return False
        normal, steps = path
        if len(normal) != 3 or not any(normal) or any(O._cross(normal, wall)):
            return False
        boundary = tuple(tuple(q*dt for q in vector) for vector, dt in history)
        return _rotation_path(steps, normal) == _rotation_path(boundary, wall)


def _back_box(cell, pose, radius, budget, *, erode=False, axis=None):
    rotation = pose.rotation()
    inverse = lambda point: tuple(sum(rotation[j][i]*point[j] for j in range(3)) for i in range(3))
    basis = tuple(tuple(sum(rotation[k][i]*cell.basis[k][j] for k in range(3))
                        for j in range(3)) for i in range(3))
    margin = Q(radius)*pose._error*(-1 if erode else 1)
    # A local coordinate along the certified axis is the same for the true
    # pose and its representative; it is neither dilated nor eroded.
    margins = tuple(Q(0) if axis is not None and not any(O._cross(
        tuple(cell.basis[k][j] for k in range(3)), axis)) else margin for j in range(3))
    if any(b+m <= a-m for a, b, m in zip(cell.lower_m, cell.upper_m, margins)):
        return None
    return V.CartesianCell(tuple(a-m for a, m in zip(cell.lower_m, margins)),
        tuple(b+m for b, m in zip(cell.upper_m, margins)), inverse(cell.origin_m), basis, budget=budget)


def _polygon_area(poly):
    return abs(sum((C._cross2(a, b) for a, b in zip(poly, poly[1:]+poly[:1])), Q(0)))/2


def _strip_moments(outside, inside, a, b, normal, bound, *, reach=None):
    """Bound a wall integral over the strip between two certified polygons.

    The true support contains the inside polygon and lies in the outside one.
    Each component of the integrand is at most bound*|normal cross x| for x in
    the convex polygon reach (the outside one unless given); that moment is
    linear, so its extreme is at a vertex.
    """
    area = _polygon_area(outside)-_polygon_area(inside)
    if area < 0:
        raise C.PressureCouplingRefused('eroded pressure domain is not enclosed by its dilation')
    corners = [O._cross(normal, tuple(u*x+v*y for x, y in zip(a, b)))
               for u, v in (outside if reach is None else reach)]
    return tuple(area*bound*max((abs(p[j]) for p in corners), default=Q(0)) for j in range(3))


def _plane_range(plane, points, radial, pose, axis=None):
    values = [sum(plane[j]*sum(pose.rotation()[j][k]*p[k] for k in range(3))
                  for j in range(3)) for p in points]
    # Optional fifth coefficient bounds the Euclidean normal error of a
    # differential component's actual posed halfspace. Both rotations preserve
    # |x|, so |(n*-n).x*| <= delta_n |x| independently of the wall pose error.
    normal_error = plane[4] if len(plane) == 5 else Q(0)
    error = radial[1]*(pose._error*_pose_norm(plane[:3], axis)+normal_error)
    return min(values)-error, max(values)+error


def _cone_status(cone, points):
    status = 1
    for a, b in zip(cone, cone[1:]+cone[:1]):
        values = [O._dot(O._cross(a, b), p) for p in points]
        if max(values) < 0:
            return 0
        if min(values) < 0:
            status = -1
    return status


def _membership(region, points, radial, pose, axis=None):
    bottom, top = region['radial']
    if radial[1] < bottom or radial[0] > top:
        return Q(0), Q(0)
    certain = radial[0] >= bottom and radial[1] <= top
    cone = _cone_status(region['cone'], points)
    if cone == 0:
        return Q(0), Q(0)
    certain &= cone == 1
    for plane in region['planes']:
        low, high = _plane_range(plane, points, radial, pose, axis)
        if low > plane[3]:
            return Q(0), Q(0)
        certain &= high <= plane[3]
    return (Q(1), Q(1)) if certain else (Q(0), Q(1))


def _ray_length(region, points, radial, bottom, top, pose, axis=None):
    bottom, top = max(bottom, region['radial'][0]), min(top, region['radial'][1])
    if top <= bottom or radial[0] >= top:
        return Q(0), Q(0)
    cone = _cone_status(region['cone'], points)
    if cone == 0:
        return Q(0), Q(0)
    maximum = max(Q(0), top-max(bottom, radial[0]))
    if cone < 0 or radial[0] <= 0:
        return Q(0), maximum
    rlo, rhi = radial
    entry = max(Q(1), bottom/rhi), max(Q(1), bottom/rlo)
    exit_ = top/rhi, top/rlo
    for plane in region['planes']:
        interval = _plane_range(plane, points, radial, pose, axis)
        if interval == (0, 0):
            if plane[3] < 0:
                return Q(0), Q(0)
        elif interval[0] > 0:
            cap = C._divide(Q(plane[3]), interval)
            exit_ = min(exit_[0], cap[0]), min(exit_[1], cap[1])
        elif interval[1] < 0:
            cap = C._divide(Q(plane[3]), interval)
            entry = max(entry[0], cap[0]), max(entry[1], cap[1])
        elif max(Q(0), interval[1])*top/rlo <= plane[3]:
            # A nearly parallel uncertain ray still cannot hit this plane if
            # its largest possible value over the ENTIRE finite radial ray is
            # inside. No division by a zero-containing coefficient is needed.
            continue
        else:
            return Q(0), maximum
    return min(max(Q(0), exit_[0]-entry[1])*rlo, maximum), min(max(Q(0), exit_[1]-entry[0])*rhi, maximum)


def moving_wall_integrals(first, second, profiles, regions, owned_box, pose, *,
                         gravity, support_radius, radius, width, max_leaves, budget, compute_density=True):
    """Certified current density and owned-wall replacement on one named arc.

    Region declarations contain actual voxel, original cone, radial interval,
    current density and trace side (None for a full native/collar voxel).
    Optional world_planes are the current physical component halfspaces
    n.x <= offset, with a nonnegative Euclidean normal-error fifth value.
    Internal _physical_planes carries the corresponding issued source record
    and exact endpoint time in the SAME order. It permits only an exact proof
    that this wall lies in a closed face; every unproved halfspace remains.
    An uncertain pose whose step history proves one rotation axis (_pose_axis)
    has exact contact with a wall normal to that axis, and regions with exact side
    weights are integrated on the representative support with their strips
    between certified inner and outer polygons bounded separately.
    This kernel grants no ownership; the issued state producer below does.
    """
    a, b = tuple(map(Q, first)), tuple(map(Q, second))
    rc, outer, gravity, width = map(Q, (support_radius, radius, gravity, width))
    if rc <= 0 or outer <= rc or gravity <= 0 or width < 0 or type(max_leaves) is not int or max_leaves < 1:
        raise C.PressureCouplingRefused('explicit positive radial support and bounded numerical integral required')
    normal, active = O._cross(a, b), []
    pose_values = (*(q for row in pose.rotation() for q in row), pose._error)
    axis = _pose_axis(pose, budget)
    # A wall plane normal to the certified axis is where the true pose puts it.
    invariant_wall = axis is not None and not any(O._cross(normal, axis))
    for original in regions:
        relevant = (0, 1) if original['side'] is None else (original['side'],)
        # An exactly zero EOS anomaly contributes neither the density integral
        # nor the pressure-ray update. Its stock/support remains in the bound
        # state; this is exact algebra, not a negligible-temperature filter.
        if all(original['density'] == row[2] for side in relevant for row in profiles[side]):
            continue
        cell = original['cell']
        extra = tuple(tuple(map(Q, p)) for p in original.get('world_planes', ()))
        if any(len(p) not in (4, 5) or (len(p) == 5 and p[4] < 0) for p in extra):
            raise C.PressureCouplingRefused('physical halfspace needs four coefficients and an optional nonnegative normal error')
        declared_extra = extra
        physical = original.get('_physical_planes', ())
        if physical and len(physical) != len(extra):
            raise C.PressureCouplingRefused('physical plane provenance must match the literal order')
        # Filter this wall's local copy only. The very same retained planes
        # feed clipping, membership, radial rays and owned/reservoir donors.
        if physical:
            extra = tuple(plane for plane, (constraint, time) in zip(extra, physical)
                          if plane[3] != 0 or not _face_on_wall(constraint, time, a, b, pose, budget))
        with V._work((*pose_values, *a, *b, *cell.lower_m, *cell.upper_m, *cell.origin_m,
                      *(q for row in cell.basis for q in row), *(q for p in original['cone'] for q in p),
                      *(q for p in declared_extra for q in p)), budget):
            region = dict(original, planes=tuple(O._box_planes(cell))+extra)
            back = _back_box(cell, pose, outer, budget, axis=axis)
            poly, contact = C.wall_polygon(back, a, b)
            # With a certified axis also keep the certified INNER polygon (the
            # eroded box cut by every halfspace moved inward by its own error)
            # and the polygon of the representative pose and planes themselves.
            # Within the radial support the true material and the representative
            # both contain the inner polygon and lie in the outer one.
            inner = posed = None
            if axis is not None:
                eroded = _back_box(cell, pose, outer, budget, erode=True, axis=axis)
                inner = C.wall_polygon(eroded, a, b)[0] if eroded is not None else ()
                posed = C.wall_polygon(_back_box(cell, pose, 0, budget), a, b)[0]
            for p, q in zip(region['cone'], region['cone'][1:]+region['cone'][:1]):
                n = O._cross(p, q)
                poly = C._clip2(poly, (-O._dot(n, a), -O._dot(n, b)), 0)
                inner = inner and C._clip2(inner, (-O._dot(n, a), -O._dot(n, b)), 0)
                posed = posed and C._clip2(posed, (-O._dot(n, a), -O._dot(n, b)), 0)
            for plane in extra:
                plane_normal = tuple(sum(plane[j]*pose.rotation()[j][k] for j in range(3)) for k in range(3))
                error = outer*(pose._error*_pose_norm(plane[:3], axis)+(plane[4] if len(plane) == 5 else 0))
                # Clip only the certified OUTER halfspace. The evaluator below
                # keeps the unresolved strip; it never treats the representative
                # plane as exact physical material support.
                poly = C._clip2(poly, (O._dot(plane_normal, a), O._dot(plane_normal, b)), plane[3]+error)
                inner = inner and C._clip2(inner, (O._dot(plane_normal, a), O._dot(plane_normal, b)), plane[3]-error)
                posed = posed and C._clip2(posed, (O._dot(plane_normal, a), O._dot(plane_normal, b)), plane[3])
        if not poly:
            continue
        if region['side'] is not None:
            weights = ((region['side'], (Q(1, 2), Q(1, 2))),)
        elif pose._error == 0:
            sides = (contact,) if contact is not None else (0, 1)
            weights = tuple((side, (Q(1, 2), Q(1, 2))) for side in sides)
        elif invariant_wall:
            # The true wall plane is normal.x = 0 in the fixed frame, so the
            # voxel's own vertices decide contact and crossing exactly.
            signed = [O._dot(normal, point) for point in cell.vertices_m]
            if min(signed) > 0 or max(signed) < 0:
                continue
            contact = 0 if min(signed) == 0 else (1 if max(signed) == 0 else None)
            sides = (contact,) if contact is not None else (0, 1)
            weights = tuple((side, (Q(1, 2), Q(1, 2))) for side in sides)
        else:
            signed = []
            for point in region['cell'].vertices_m:
                value = sum(normal[k]*sum(pose.rotation()[j][k]*point[j] for j in range(3)) for k in range(3))
                error = pose._error*sum(map(abs, point))*sum(map(abs, normal))
                signed.append((value-error, value+error))
            crosses = min(v[1] for v in signed) < 0 < max(v[0] for v in signed)
            weights = tuple((side, (Q(1, 2) if crosses else Q(0), Q(1, 2))) for side in (0, 1))
        region.update(poly=poly, weights=weights, inner=inner, posed=posed)
        active.append(region)
    back_owned = _back_box(owned_box, pose, outer, budget, axis=axis)
    native_poly, _ = C.wall_polygon(back_owned, a, b)
    owned = dict(planes=O._box_planes(owned_box), radial=(rc, outer), cone=())
    # Q is orthogonal and ||Q-Qtrue||_2 <= delta. For r<=R each local
    # Cartesian coordinate differs by at most R*delta. Therefore the wall
    # polygon of the eroded box lies inside the true domain, which lies inside
    # the dilated polygon. Bound that thin strip by its exact uv area instead
    # of treating every triangle touching a boundary as wholly uncertain.
    low2, high2 = owned_box.radial_bounds_squared_m2
    inner_poly, strip_area = native_poly, Q(0)
    certain_domain = rc**2 <= low2 and high2 <= outer**2
    if certain_domain:
        inner = _back_box(owned_box, pose, outer, budget, erode=True, axis=axis)
        inner_poly = C.wall_polygon(inner, a, b)[0] if inner is not None else ()
        strip_area = _polygon_area(native_poly)-_polygon_area(inner_poly)
        if strip_area < 0:
            raise C.PressureCouplingRefused('eroded pressure domain is not enclosed by its dilation')
    allowance = width/max(1, 2*(len(active)+1))
    delta, leaves = [(Q(0), Q(0)) for _ in range(3)], 0
    for region_index, region in enumerate(active if compute_density else ()):
        def anomaly(points, radial, moment):
            membership = _membership(region, points, radial, pose, axis)
            if membership == (0, 0):
                return ((Q(0), Q(0)),)*3
            lower, upper = max(rc, region['radial'][0], radial[0]), min(outer, region['radial'][1], radial[1])
            difference = (Q(0), Q(0))
            for side, weight in region['weights']:
                old = C._density_range(profiles[side], (lower, upper))
                difference = C._add(difference, C._mul((region['density']-old[1], region['density']-old[0]), weight))
            if membership == (1, 1) and difference[0] == difference[1]:
                return tuple(C._scale(v, -gravity*difference[0]/3) for v in
                    C._radial_linear_mean(points, radial, normal, rc=rc))
            kernel = lower-rc**3/lower**2, upper-rc**3/upper**2
            return tuple(C._scale(C._mul(C._mul(C._mul(difference, membership), kernel), v), -gravity/3) for v in moment)
        # These live exact coefficients are not included in the triangle's own
        # workspace. Charge their widths before any evaluator products/GCDs.
        with V._work((*pose_values, region['density'], *(v for row in region['planes'] for v in row)), budget):
            bands = strip = None
            try:
                exact_planes = pose._error == 0 and all(len(p) == 4 or p[4] == 0 for p in region['planes'])
                if ((exact_planes or region['inner'] is not None) and
                        all(weight[0] == weight[1] for _, weight in region['weights'])):
                    bottom, top = max(rc, region['radial'][0]), min(outer, region['radial'][1])
                    breaks = sorted({bottom, top, *(v for side, _ in region['weights']
                        for row in profiles[side] for v in row[:2] if bottom < v < top)})
                    bands = []
                    for low, high in zip(breaks, breaks[1:]):
                        sample = (low+high)/2
                        difference = sum(((region['density']-C._density_range(profiles[side], (sample, sample))[0])*weight[0]
                                          for side, weight in region['weights']), Q(0))
                        if difference:
                            bands.append((low, high, -gravity*difference/3))
                    if not exact_planes:
                        # Integrate the representative support exactly as an
                        # exact pose would. It differs from the true material
                        # only inside the strip between the inner and outer
                        # polygons, where each band's integrand is at most
                        # |coefficient|*(r-rc^3/r^2)*|normal cross x|, with an
                        # increasing radial factor. The strip may widen the
                        # result by at most half the allowance; a larger one
                        # leaves the region to the general enclosure below.
                        strip = _strip_moments(region['poly'], region['inner'], a, b, normal, max(
                            (abs(coefficient)*(high-rc**3/high**2) for _, high, coefficient in bands), default=Q(0)))
                        if 4*max(strip) > allowance:
                            bands = strip = None
                if bands is not None:
                    shape, share = (region['poly'], allowance) if strip is None else (region['posed'], allowance/2)
                    bounds, used = ((Q(0), Q(0)),)*3, 0
                    for low, high, coefficient in bands:
                        if used >= max_leaves:
                            raise C.PressureCouplingRefused('radial density bands exhaust the declared per-region leaf budget')
                        value, count = C._integrate_radial_shell(shape, a, b, low, high, rc,
                            width=share/(len(bands)*abs(coefficient)), max_leaves=max_leaves-used, budget=budget)
                        bounds = tuple(C._add(v, C._scale(w, coefficient)) for v, w in zip(bounds, value))
                        used += count
                    if strip is not None:
                        bounds = tuple((pair[0]-e, pair[1]+e) for pair, e in zip(bounds, strip))
                else:
                    # An uncertain posed plane still needs its existing full
                    # physical-membership enclosure; no representative plane
                    # or radial strip is silently promoted to exact support.
                    bounds, used = C._integrate(region['poly'], a, b, anomaly, width=allowance, max_leaves=max_leaves, budget=budget)
            except C.PressureCouplingRefused as error:
                # A certified axis, and the strip route when it ran with its
                # bound and the width its exact integral was given, are named;
                # every other record keeps exactly the keys below.
                error.add_note('PRESSURE_REGION_CONTEXT '+json.dumps(dict(
                    **({} if axis is None else dict(pose_axis=list(map(V._encoded, axis)))),
                    **({} if strip is None else dict(certified_density_strip=list(map(V._encoded, strip)),
                                                     integral_width=V._encoded(allowance/2))),
                    operation='current-density-anomaly', region_index=region_index, active_regions=len(active),
                    total_wall_width=V._encoded(width), gravity=V._encoded(gravity),
                    support_radius=V._encoded(rc), outer_radius=V._encoded(outer),
                    density=V._encoded(region['density']), radial=list(map(V._encoded, region['radial'])),
                    weights=[[side, list(map(V._encoded, weight))] for side, weight in region['weights']],
                    planes=[[V._encoded(q) for q in row] for row in region['planes']],
                    cone=[[V._encoded(q) for q in row] for row in region['cone']],
                    profiles=[[[V._encoded(q) for q in row] for row in profile] for profile in profiles],
                    pose_rotation=[[V._encoded(q) for q in row] for row in pose.rotation()],
                    pose_error=V._encoded(pose._error), cell=region['cell'].record()),
                    sort_keys=True, separators=(',', ':')))
                raise
        delta = [C._add(v, w) for v, w in zip(delta, bounds)]; leaves += used
    def pressure(points, radial, moment):
        membership = (Q(1), Q(1)) if certain_domain else _membership(owned, points, radial, pose, axis)
        if membership == (0, 0):
            return ((Q(0), Q(0)),)*3
        lower, upper = max(rc, radial[0]), min(outer, radial[1])
        total = [(Q(0), Q(0)) for _ in range(3)]
        centre = tuple(sum(p[j] for p in points)/3 for j in range(3))
        linear = O._cross(normal, centre)
        average = C._radial_linear_mean(points, radial, normal) if membership == (1, 1) else None
        for profile in profiles:
            row = next((r for r in profile if r[0] <= radial[0] and r[1] >= radial[1]), None)
            if row is not None and average is not None:
                _, top, rho, ptop = row
                for j in range(3):
                    constant = (ptop+gravity*rho*top)*linear[j]/2
                    total[j] = C._add(total[j], C._add((constant, constant), C._scale(average[j], -gravity*rho/2)))
            else:
                pressure_range = C._pressure(profile, upper, gravity)/2, C._pressure(profile, lower, gravity)/2
                total = [C._add(v, C._mul(pressure_range, w)) for v, w in zip(total, moment)]
        changed = (Q(0), Q(0))
        for region in active:
            for side, weight in region['weights']:
                for bottom, top, rho, _ in profiles[side]:
                    if region['density'] == rho:
                        continue
                    length = _ray_length(region, points, (lower, upper), bottom, top, pose, axis)
                    changed = C._add(changed, C._scale(C._mul(length, weight), gravity*(region['density']-rho)))
        return tuple(C._scale(C._mul(C._add(v, C._mul(changed, w)), membership), -1) for v, w in zip(total, moment))
    with V._work((*pose_values, *(v for row in owned['planes'] for v in row),
                  *(v for region in active for row in region['planes'] for v in row)), budget):
        exact_rays = pose._error == 0 and all(
            all(len(plane) == 4 or plane[4] == 0 for plane in region['planes']) and
            all(weight[0] == weight[1] for _, weight in region['weights']) for region in active)
        strips, receiver = None, inner_poly
        if not exact_rays and axis is not None and certain_domain and all(region['inner'] is not None and
                all(weight[0] == weight[1] for _, weight in region['weights']) for region in active):
            # Representative receiver and donors keep every shared edge shared.
            # A donor's column above a wall point differs from the true one by
            # at most the ray length inside its strip. A receiver at radius r
            # below a strip point at radius s carries r dr against that point's
            # own s ds, and the integral of r from rc to s is (s^2-rc^2)/2. So
            # a strip changes the wall integral of its ray length by at most
            # its uv area times (top^2-rc^2)/(2*top), the largest ratio on its
            # band. All donor strips together may use half the allowance. The
            # receiver's own strip is bounded after the integral, as always.
            strips = [Q(0)]*3
            for region in active:
                head = Q(0)
                for side, weight in region['weights']:
                    for bottom, top, rho, _ in profiles[side]:
                        low, high = max(rc, bottom, region['radial'][0]), min(outer, top, region['radial'][1])
                        if low < high:
                            head += gravity*abs(region['density']-rho)*weight[0]*(high**2-rc**2)/(2*high)
                strips = [s+e for s, e in zip(strips, _strip_moments(
                    region['poly'], region['inner'], a, b, normal, head, reach=native_poly))]
            if 4*max(strips) > allowance:
                strips = None
            else:
                receiver = C.wall_polygon(_back_box(owned_box, pose, 0, budget), a, b)[0]
        try:
            if exact_rays or strips is not None:
                radial_profiles = tuple((*row, Q(1, 2)) for profile in profiles for row in profile)
                donors = []
                for region in active:
                    shape = region['poly'] if strips is None else region['posed']
                    for side, weight in region['weights']:
                        for bottom, top, rho, _ in profiles[side]:
                            low, high = max(rc, bottom, region['radial'][0]), min(outer, top, region['radial'][1])
                            coefficient = gravity*(region['density']-rho)*weight[0]
                            if low < high and coefficient and shape:
                                donors.append((shape, low, high, coefficient))
                value, used = C._integrate_radial_pressure(receiver, a, b, radial_profiles, tuple(donors),
                    rc, outer, gravity, width=allowance if strips is None else allowance/2,
                    max_leaves=max_leaves, budget=budget)
                removed = tuple(C._scale(pair, -1) for pair in value)
                if strips is not None:
                    removed = tuple((pair[0]-e, pair[1]+e) for pair, e in zip(removed, strips))
            else:
                removed, used = C._integrate(inner_poly, a, b, pressure, width=allowance, max_leaves=max_leaves, budget=budget)
        except C.PressureCouplingRefused as error:
            error.add_note('PRESSURE_OWNED_CONTEXT '+json.dumps(dict(
                operation='current-owned-pressure', exact_radial_rays=exact_rays,
                **({} if axis is None else dict(pose_axis=list(map(V._encoded, axis)))),
                **({} if strips is None else dict(certified_donor_strips=list(map(V._encoded, strips)),
                                                  integral_width=V._encoded(allowance/2))),
                width=V._encoded(allowance), max_leaves=max_leaves,
                wall_rays=[[V._encoded(q) for q in ray] for ray in (a, b)],
                polygon=[[V._encoded(q) for q in p] for p in receiver],
                gravity=V._encoded(gravity), support_radius=V._encoded(rc), outer_radius=V._encoded(outer),
                profiles=[[[V._encoded(q) for q in row] for row in profile] for profile in profiles],
                pose_rotation=[[V._encoded(q) for q in row] for row in pose.rotation()],
                pose_error=V._encoded(pose._error), owned_box=owned_box.record(),
                regions=[dict(cell=r['cell'].record(), density=V._encoded(r['density']),
                    radial=list(map(V._encoded, r['radial'])),
                    cone=[[V._encoded(q) for q in row] for row in r['cone']],
                    world_planes=[[V._encoded(q) for q in row] for row in r.get('world_planes', ())],
                    weights=[[side, list(map(V._encoded, weight))] for side, weight in r['weights']],
                    polygon=[[V._encoded(q) for q in p] for p in r['poly']]) for r in active]),
                sort_keys=True, separators=(',', ':')))
            raise
        if strip_area:
            # On the omitted true strip use the whole radial support, including
            # every retained density anomaly on a possibly intersected ray.
            # Sum-absolute bounds may overcount, but can never hide a contrast.
            pressure_bound = sum((max(abs(ptop), abs(ptop+gravity*rho*(top-bottom)))
                for profile in profiles for bottom, top, rho, ptop in profile), Q(0))/2
            for region in active:
                for side, weight in region['weights']:
                    pressure_bound += sum((gravity*abs(region['density']-rho)*(top-bottom)*weight[1]
                        for bottom, top, rho, _ in profiles[side]), Q(0))
            points = [tuple(u*x+v*y for x, y in zip(a, b)) for u, v in native_poly]
            moments = [O._cross(normal, p) for p in points]
            error = [strip_area*pressure_bound*max(abs(p[j]) for p in moments) for j in range(3)]
            removed = tuple((pair[0]-e, pair[1]+e) for pair, e in zip(removed, error))
    delta, removed = _rotate_bounds(delta, pose), _rotate_bounds(removed, pose)
    if max(v[1]-v[0] for v in (*delta, *removed)) > width:
        raise C.PressureCouplingRefused('pose uncertainty exceeds the requested current pressure torque width')
    return delta, removed, leaves+used


def _density(material, energy, masses, budget):
    """The literal current common-material EOS, with no thermal projection."""
    values = (energy, *masses, material.heat_capacity_j_kg_k, material.density_kg_m3,
              material.expansion_per_k, material.reference_temperature_k,
              *material.temperature_range_k, material.max_relative_density_anomaly)
    with V._work(values, budget):
        mass = sum(masses, Q(0))
        if mass <= 0 or any(v < 0 for v in masses):
            raise C.PressureCouplingRefused('positive finite current material mass is required')
        temperature = energy/(mass*Q(material.heat_capacity_j_kg_k))
        if not Q(material.temperature_range_k[0]) <= temperature <= Q(material.temperature_range_k[1]):
            raise C.PressureCouplingRefused('current spatial temperature exceeds the declared native material envelope')
        rho = Q(material.density_kg_m3)
        anomaly = -rho*Q(material.expansion_per_k)*(temperature-Q(material.reference_temperature_k))
        if abs(anomaly) > rho*Q(material.max_relative_density_anomaly):
            raise C.PressureCouplingRefused('current spatial density exceeds the declared Boussinesq envelope')
        return rho+anomaly, temperature


def spatial_pressure_correction(sphere, moving, support, base_port, funding, collar, state,
                                spatial_state, pose, *, max_torque_width_n_m, max_leaves, budget):
    """Consume the actual current spatial exterior and fixed regional grid.

    Each carried FV field is constant only on its actual physical cell. The
    planar heat surrogate is never used to locate a pressure-wall intersection.
    Original profiles are subtracted references, not a second active inventory.
    """
    from . import integration_material as M, integration_ports as P, integration_patch_heat as PH
    from . import integration_exterior_mesh as E
    from .integration_collar_geometry import FullCellFunding
    from .integration_radial_pressure import RadialPressureTrace
    from .integration_spatial_owner import SpatialExteriorState
    from .regional_collar3d import PreparedRegionalCollar3D, RegionalCollarState
    from .resources import WorkBudget
    if (type(funding) is not FullCellFunding or type(collar) is not PreparedRegionalCollar3D or
            type(state) is not RegionalCollarState or type(spatial_state) is not SpatialExteriorState or
            type(pose) is not F.CurrentForcePose or type(base_port) is not RadialPressureTrace or
            type(support) is not P.TraceSupport or type(budget) is not WorkBudget or
            any(v is not budget for v in (funding._resource, collar._budget, spatial_state._budget, pose._resource))):
        raise C.PressureCouplingRefused('issued current spatial/native states, physical pose and one shared budget required')
    if (type(max_torque_width_n_m) not in (Q, int) or max_torque_width_n_m < 0 or
            type(max_leaves) is not int or max_leaves < 1):
        raise C.PressureCouplingRefused('exact nonnegative torque width and positive leaf limit required')
    M.bound_moving(moving, sphere)
    # The immutable snapshot sizes admit their record/array copies. Per-cell
    # exact arithmetic is charged separately, one live operation at a time.
    size = (262144+5*spatial_state._snapshot.nbytes+8*len(base_port._record)+
            4*funding._snapshot.nbytes+16384*(math.prod(collar.cells)+support.edges))
    with budget.reserve(size, category='current-spatial-pressure'):
        funded, plan, current, placed = funding.descriptor(), collar.descriptor(), spatial_state.record(), pose.descriptor()
        binding = dict(sphere_state_id=sphere.state_id, network_id=sphere.network.network_id,
            material_id=sphere.material.material_id, moving_id=moving.moving_id)
        time = state.native_state.descriptor()['time_s']
        if (funded['source'] != binding or funded['collar_plan_id'] != collar.plan_id or
                funded['volume_map_id'] != plan['volume_map_id'] or current['funding_id'] != funding.funding_id or
                base_port.source_state_id != sphere.state_id or base_port.moving_id != moving.moving_id or
                base_port.material_id != sphere.material.material_id or base_port.support_id != support.support_id or
                support.network_id != sphere.network.network_id or placed['source'] != binding or
                placed['funding_id'] != funding.funding_id or current['time_s'] != time or
                W._decode(placed['time_s']) != Q(time) or current['support_id'] != placed['support_id'] or
                current['trajectory_id'] != placed['trajectory_id'] or
                (current['intervals'] and current['collar_state_id'] != state.result_id) or
                (not current['intervals'] and state.native_state.result_id != funded['native_initial_state_id'])):
            raise C.PressureCouplingRefused('stale source, physical pose, current spatial/native state or clock')
        mesh = current['thermal_mesh']
        if (mesh['funding_id'] != funding.funding_id or mesh['source'] != binding or
                mesh['support_id'] != current['support_id'] or mesh['trajectory_id'] != current['trajectory_id'] or
                W._decode(mesh['time_s']) != Q(time) or mesh['grid_id'] != current['grid_id'] or
                mesh['trajectory_segments'] != current['trajectory']['segments']):
            raise C.PressureCouplingRefused('spatial field has stale physical-support provenance')
        native, datum = collar._native, base_port.datum
        material = native._material
        if material.reference_temperature_k != datum.reference_temperature_k or material.composition_density_contrast_kg_m3 != 0:
            raise C.PressureCouplingRefused('matching literal thermal EOS and explicit background composition are required')
        fields = collar._fields(state)
        cells = collar.cell_geometries()
        if [c.record() for c in cells] != funded['cell_geometries']:
            raise C.PressureCouplingRefused('current active cells differ from the funded exclusion geometry')
        rc, radius = Q(datum.support_radius_m), Q(datum.reference_radius_m)
        densities, temperatures, regions = [], [], []
        masses = fields['component_mass_kg'].reshape(len(funded['component_keys']), -1)
        for i, (cell, energy) in enumerate(zip(cells, fields['enthalpy_j'].flat)):
            low, high = cell.radial_bounds_squared_m2
            if low < rc**2 or high > radius**2:
                raise C.PressureCouplingRefused('current active cell outside the declared radial pressure support')
            rho, temperature = _density(material, Q(float(energy)), tuple(Q(float(v)) for v in masses[:, i]), budget)
            densities.append(rho); temperatures.append(temperature)
            regions.append(dict(cell=cell, cone=(), radial=(rc, radius), density=rho, patch_id=None))
        thermal = {row['logical_cell_id']: row for row in mesh['cells'] if row['kind'] == 'exterior'}
        if len(thermal) != len(current['cells']) or set(thermal) != {row['cell_id'] for row in current['cells']}:
            raise C.PressureCouplingRefused('current spatial fields and physical supports differ')
        exterior_densities, exterior_temperatures = [], []
        for row in current['cells']:
            cell_row = thermal[row['cell_id']]
            if row['source_key'] != cell_row['source_key']:
                raise C.PressureCouplingRefused('current logical cell source ownership differs')
            exact = row['exact']
            density, temperature = _density(material, W._decode(exact['enthalpy_j']),
                tuple(W._decode(exact['component_mass_kg:'+str(i)]) for i in range(len(funded['component_keys']))), budget)
            physical = E.resolve_physical_support(mesh, cell_row)
            voxel = V.CartesianCell.from_record(physical['voxel'], budget=budget)
            layer = physical['radial_layer']
            if W._decode(layer['radius_m']) != radius or layer['convention'] != V.PHYSICAL_RADIAL_SHELL:
                raise C.PressureCouplingRefused('current cell pressure geometry uses another radial convention/radius')
            rb, rt = radius-W._decode(layer['bottom_depth_m']), radius-W._decode(layer['top_depth_m'])
            if not rc <= rb < rt <= radius:
                raise C.PressureCouplingRefused('current spatial radial band lies outside the pressure support')
            cone = tuple(tuple(map(W._decode, p)) for p in physical['original_cone'])
            regions.append(dict(cell=voxel, cone=cone, radial=(rb, rt), density=density, patch_id=row['source_key'][0]))
            exterior_densities.append(density); exterior_temperatures.append(temperature)
        inner = [c for i, c in enumerate(cells) if all(s.start <= int(j) < s.stop for s, j in
                 zip(collar._inner, np.unravel_index(i, collar.cells)))]
        owned = V.CartesianCell(tuple(min(c.lower_m[j] for c in inner) for j in range(3)),
            tuple(max(c.upper_m[j] for c in inner) for j in range(3)), inner[0].origin_m, inner[0].basis, budget=budget)
        rows, offsets = base_port.record()['layer_rows'], base_port.layer_offsets
        profiles = [tuple(tuple(PH._rational(row[k]) for k in
                    ('bottom_radius_m', 'top_radius_m', 'effective_density_kg_m3', 'pressure_top_pa'))
                    for row in rows[int(offsets[i]):int(offsets[i+1])]) for i in range(base_port.points)]
        order = {p: i for i, p in enumerate(sphere.network.plate_ids)}
        delta = [[(Q(0), Q(0)) for _ in range(3)] for _ in order]
        removed = [[(Q(0), Q(0)) for _ in range(3)] for _ in order]
        # Sparse original patch contacts select exterior cells. Native cells
        # are bounded by the one active box, not compared to every exterior row.
        native_regions, by_patch = regions[:len(cells)], {}
        for region in regions[len(cells):]:
            by_patch.setdefault(region['patch_id'], []).append(region)
        outer = V.CartesianCell(tuple(min(c.lower_m[j] for c in cells) for j in range(3)),
            tuple(max(c.upper_m[j] for c in cells) for j in range(3)), cells[0].origin_m, cells[0].basis, budget=budget)
        back_outer = _back_box(outer, pose, radius, budget)
        edges = [e for e in range(support.edges) if any(p in by_patch for p in support.patch_ids[e]) or
                 C.wall_polygon(back_outer, support.start[e], support.end[e])[0]]
        width = Q(max_torque_width_n_m)/max(1, len(edges))
        leaves = 0
        for e in edges:
            selected = [dict(region, side=None) for region in native_regions]
            for side, patch in enumerate(support.patch_ids[e]):
                selected.extend(dict(region, side=side) for region in by_patch.get(patch, ()))
            d, w, used = moving_wall_integrals(support.start[e], support.end[e], profiles[2*e:2*e+2],
                selected, owned, pose, gravity=datum.gravity_m_s2, support_radius=rc, radius=radius,
                width=width, max_leaves=max_leaves, budget=budget)
            leaves += used
            for side, sign in ((0, 1), (1, -1)):
                plate = order[support.plates[e][side]]
                delta[plate] = [C._add(a, C._scale(b, sign)) for a, b in zip(delta[plate], d)]
                removed[plate] = [C._add(a, C._scale(b, sign)) for a, b in zip(removed[plate], w)]
        combined = [[(a[0]-b[1], a[1]-b[0]) for a, b in zip(da, re)] for da, re in zip(delta, removed)]
        arrays, residuals = {}, {}
        for name, bounds in (('density_update_torque_n_m', delta), ('removed_wall_torque_n_m', removed),
                             ('physical_exterior_correction_n_m', combined)):
            values = np.asarray([[float((a+b)/2) for a, b in row] for row in bounds])
            if not np.isfinite(values).all():
                raise C.PressureCouplingRefused('current pressure torque cannot be represented as binary64')
            arrays[name] = values
            residuals[name] = [[V._encoded(Q(float(v))-(a+b)/2) for v, (a, b) in zip(row, exact)]
                               for row, exact in zip(values, bounds)]
        encode = lambda bounds: [[list(map(V._encoded, pair)) for pair in row] for row in bounds]
        arrays.update(current_cell_density_kg_m3=np.asarray(list(map(float, densities))).reshape(collar.cells),
                      spatial_cell_density_kg_m3=np.asarray(list(map(float, exterior_densities))))
        metadata = dict(schema='atlas.current-spatial-pressure-correction.v1', source=binding,
            base_port_id=base_port.port_id, support_id=support.support_id, datum_id=datum.datum_id,
            funding_id=funding.funding_id, collar_plan_id=collar.plan_id, collar_state_id=state.result_id,
            native_state_id=state.native_state.result_id, time_s=time, native_plan_id=native.plan_id,
            plate_ids=list(sphere.network.plate_ids), volume_map_id=plan['volume_map_id'], owned_box=owned.record(),
            current_pose=placed, spatial_state_id=spatial_state.state_id, thermal_mesh_id=current['thermal_mesh_id'],
            logical_cell_ids=[row['cell_id'] for row in current['cells']],
            exact_current_cell_density_kg_m3=list(map(V._encoded, densities)),
            exact_spatial_cell_density_kg_m3=list(map(V._encoded, exterior_densities)),
            exact_spatial_temperature_k=list(map(V._encoded, exterior_temperatures)),
            density_update_bounds_n_m=encode(delta), removed_wall_bounds_n_m=encode(removed),
            physical_exterior_correction_bounds_n_m=encode(combined),
            binary64_minus_enclosure_midpoint_n_m=residuals,
            request=dict(max_torque_width_n_m=V._encoded(Q(max_torque_width_n_m)), max_leaves=max_leaves),
            integration_leaves=leaves, source_shadow='old owned density subtracted on actual current support',
            remainder='current spatial cell fields on moving cone/shell intersect fixed exterior voxels',
            pressure='hydrostatic force reference, not solved material mean stress',
            partition='Q*b_D1+delta_density-actual_current_owned_wall; native Q1 counterterm separate',
            scope='one current common rigid exterior pose; distinct solved plate rates do not advance this support')
        snapshot = RegionalMechanicalSnapshot(metadata, arrays)
        out = object.__new__(C.OwnedPressureCorrection)
        object.__setattr__(out, '_snapshot', snapshot); object.__setattr__(out, '_resource', budget)
        lease = budget.reserve(8192+2*snapshot.nbytes, category='current-spatial-pressure-retained')
        lease.__enter__(); weakref.finalize(out, lease.__exit__, None, None, None)
        return out
