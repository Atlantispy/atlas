"""Exact zero-area certificates for positive-ray moving radial interfaces.

A face point is alpha*a(t)+beta*b(t), alpha,beta>=0. If an ACTUAL retained
homogeneous support halfspace has n(t).a(t)<=0 and n(t).b(t)<=0, with at least
one strict throughout 0<t<=T, its admitted face is at most a line. This proves
zero area, not zero material velocity, approximate incidence or a small sliver.
Two identically zero generator values do not prove exclusion.

Only exact coaxial rigid normal/ray paths are used. Common prior rotations
cancel; unequal prior phases and noncommuting histories decline unless the
normal or ray is exactly axial. Unsupported cases retain ordinary enclosure.

The fixed voxel is an actual retained clip of the measured face too. A voxel
wall through the sphere centre is therefore admitted as one more homogeneous
halfspace; a wall with any nonzero offset is not. Two retained halfspaces may
also exclude jointly: if generator a starts EXACTLY in both planes, f1(a)<=0,
f2(b)<=0 and f1(a)f2(b)-f1(b)f2(a)>0 throughout 0<t<=T, then
alpha*f1(a)+beta*f1(b)>=0 and alpha*f2(a)+beta*f2(b)>=0 force alpha*beta=0, so
the admitted face lies on the two generator rays. Writing fi(a)=t*ui(t), the
determinant is t*(u1*f2(b)-f1(b)*u2); its bracket is bounded on the closed
interval with rational sine/cosine remainders, never sampled.

Exactly opposing homogeneous cuts instead force n(t).x=0. If at least one
interface generator has a constant nonzero dot product with that normal,
the interface plane is distinct from the retained plane at every instant.
Their intersection has at most one dimension, so its area and flux vanish.
This is an exact incidence proof, not rounding a small enclosure to zero.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import hashlib
from pathlib import Path

from . import integration_volume as V, integration_volume_overlap as O

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def source_digest():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise V.VolumeError('moving-interface exclusion source changed after loading')
    return _LOADED


def _ray_path(ray, G):
    direction = G._load_vec(ray['direction'])
    omega = G._load_vec(ray['angular_velocity_rad_s'])
    history = G._history(ray.get('prior_rotations', ()))
    theta = tuple(sum((w[j]*dt for w, dt in history), Q(0)) for j in range(3))
    return direction, theta, omega, tuple(w for w, dt in history if dt)


def _generator_form(normal_path, ray_path, sign, duration):
    """Exact f(t)=sign*n(t).r(t) of one retained halfspace along one generator.

    Returns (d, None, rule) for an exactly constant value, (d, (A, N, |k|^2,
    |k|^2 T^2), None) for the Rodrigues form documented in ``_nonpositive``,
    or None where no exact coaxial form exists. The caller owns the work lease.
    """
    normal, theta_n, omega_n = normal_path
    ray, theta_r, omega_r, prior = ray_path
    vectors = (theta_n, omega_n, omega_r, *prior)
    axis = next((v for v in vectors if any(v)), (Q(0),)*3)
    if any(any(O._cross(axis, v)) for v in vectors):
        return None
    n = tuple(sign*q for q in normal)
    d = O._dot(n, ray)
    # An axial normal/ray is invariant under EVERY admitted rotation,
    # including unequal prior phases. Otherwise only identical phases
    # cancel; do not silently evaluate an unrotated starting dot product.
    if not any(axis) or not any(O._cross(axis, n)) or not any(O._cross(axis, ray)):
        return d, None, 'exact-axial-or-stationary-constant'
    if theta_n != theta_r:
        return None
    k = tuple(r-p for r, p in zip(omega_r, omega_n))
    kk = O._dot(k, k)
    if not kk:
        return d, None, 'exact-common-rotation-constant'
    angle_squared = kk*duration*duration
    if angle_squared > 1:
        return None
    return d, (d-O._dot(n, k)*O._dot(ray, k)/kk, O._dot(n, O._cross(k, ray)), kk, angle_squared), None


def _nonpositive(normal_path, ray_path, sign, duration, arena):
    """Return (strict, exact coefficients, rule), or no sign certificate.

    With k=omega_ray-omega_normal, x=|k|t and equal prior phases, Rodrigues
    gives f(t)=d+A(cos(x)-1)+(N/|k|)sin(x), where
      d=n.r, A=d-(n.k)(r.k)/|k|^2, N=n.(k cross r).
    For 0<x<=1, cos(x)-1<0 and sin(x)>0. No transcendental value or rounded
    endpoint is needed. For an opposing cosine coefficient, sin(x)<=x and
    cos(x)>=1-x^2/2 give a closed strict derivative upper bound. The alternate
    negative value envelope uses only
    1-cos(x)<=x^2/2 and sin(x)<=x. Its strict upper bound is closed in time.
    """
    normal, theta_n, omega_n = normal_path
    ray, theta_r, omega_r, prior = ray_path
    operands = (*normal, *theta_n, *omega_n, *ray, *theta_r, *omega_r,
                *(q for w in prior for q in w), duration)
    with V._work(operands, arena.resource):
        arena.work(128+16*len(prior))
        form = _generator_form(normal_path, ray_path, sign, duration)
        if form is None:
            return None
        d, moving, rule = form
        if moving is None:
            return (d < 0, (d,), rule) if d <= 0 else None
        if d > 0:
            return None
        A, N, kk, angle_squared = moving
        coefficients = (d, A, N, kk, duration, angle_squared)
        with V._work(coefficients, arena.resource):
            if A >= 0 and N <= 0:
                return (d < 0 or A > 0 or N < 0, coefficients,
                        'exact-Rodrigues-same-sign-departure')
            if N <= 0:
                derivative_upper = max(-A, Q(0))*kk*duration+N*(1-angle_squared/2)
                if derivative_upper < 0:
                    return (True, (*coefficients, derivative_upper),
                            'strict-negative-Rodrigues-derivative')
            upper = d+max(-A, Q(0))*angle_squared/2+max(N, Q(0))*duration
            if upper < 0:
                return True, (*coefficients, upper), 'strict-negative-Rodrigues-envelope'
    return None


def _product(a, b):
    values = tuple(x*y for x in a for y in b)
    return min(values), max(values)


def _departure_bounds(d, moving, duration):
    """Closed bounds on 0<=t<=T of f and u, where f(t)=d+t*u(t) exactly.

    f=d-A|k|^2 t^2 g/2+N t s with s=sin(x)/x in [1-x^2/6,1] and
    g=2(1-cos(x))/x^2 in [0,1], x^2=|k|^2 t^2<=|k|^2 T^2<=1, so
    u=N s-A|k|^2 t g/2 and t g ranges within [0,T]. Interval products only
    widen these exact enclosures.
    """
    if moving is None:
        return (d, d), (Q(0), Q(0))
    A, N, kk, angle_squared = moving
    time = Q(0), duration
    sine = _product((N, N), (1-angle_squared/6, Q(1)))
    cosine = _product((A*kk/2,)*2, time)
    u = sine[0]-cosine[1], sine[1]-cosine[0]
    departure = _product(time, u)
    return (d+departure[0], d+departure[1]), u


def _pair_exclusion(first, second, shared, duration, arena):
    """Joint exclusion by two halfspaces sharing one exactly incident generator.

    ``first``/``second`` hold each halfspace's two generator forms. Returns the
    certified (u1 upper, f2(other) upper, bracket lower) or None. A generator
    that starts merely near either plane declines here.
    """
    forms = first[shared], first[1-shared], second[shared], second[1-shared]
    operands = tuple(q for d, moving, _ in forms for q in (d, *(moving or ())))
    with V._work((*operands, duration), arena.resource, pairs=16):
        arena.work(96)
        if first[shared][0] or second[shared][0]:
            return None
        (_, u1), (f1, _), (_, u2), (f2, _) = (_departure_bounds(d, moving, duration)
                                              for d, moving, _ in forms)
        if u1[1] > 0 or f2[1] > 0:
            return None
        lower = _product(u1, f2)[0]-_product(f1, u2)[1]
        return (u1[1], f2[1], lower) if lower > 0 else None


def _opposite_exclusion(halfspaces, paths, duration, arena):
    """Prove lower-dimensional contact from actual opposing physical cuts.

    Canonical normals identify only exactly proportional cuts with identical
    rigid paths. A negative signed scale makes their inequalities an equality.
    The generator witness must be CONSTANT and nonzero throughout the interval;
    initial non-incidence alone is insufficient. Unsupported paths decline.
    """
    from .integration_regional_inventory import _width
    with arena.resource.reserve(8192+64*_width(halfspaces),
                                category='interface-opposite-paths'):
        seen = {}
        for row in halfspaces:
            name, sign, plane, wall = row
            normal, theta, omega = plane
            operands = tuple(q for vector in plane for q in vector)
            with V._work(operands, arena.resource, pairs=8):
                arena.work(64)
                pivot = next(q for q in normal if q)
                key = (tuple(q/pivot for q in normal), theta, omega)
                signed_pivot = sign*pivot
                previous = seen.get(key)
                if previous is None:
                    seen[key] = (row, signed_pivot)
                    continue
                first, first_pivot = previous
                if (signed_pivot > 0) == (first_pivot > 0):
                    continue
                scale = signed_pivot/first_pivot
            for generator, path in enumerate(paths):
                ray, phase, velocity, prior = path
                values = (*(q for vector in first[2] for q in vector),
                          *ray, *phase, *velocity,
                          *(q for vector in prior for q in vector), duration, scale)
                with V._work(values, arena.resource, pairs=8):
                    arena.work(128+16*len(prior))
                    form = _generator_form(first[2], path, first[1], duration)
                    if form is None or form[1] is not None or not form[0]:
                        continue
                    constant, _, rule = form
                    arena.keep((*values, constant), 32)
                    return dict(method='exact-opposite-halfspaces-transverse-generator',
                        source_sha256=source_digest(),
                        constraint_names=[first[0], name],
                        halfspace_signs=[first[1], sign],
                        fixed_voxel_walls=[first[3], wall],
                        transverse_generator=generator, generator_rule=rule,
                        normal_scale=V._encoded(scale), constant_dot=V._encoded(constant),
                        duration_s=V._encoded(duration),
                        open_interval='0 <= t <= duration',
                        area_rule='opposing actual cuts force a plane distinct from the interface plane; intersection is at most a line')
    return None


def radial_cap_zero_area(constraint, layer, cell, duration, arena):
    """Prove a voxel-capped positive ray cone lies inside the hollow core.

    For an ACTUAL wall h.x<=d, d>=0, require closed positive lower bounds
    0<l_i<=h.r_i(t) for the WHOLE interval. Then alpha*l_0+beta*l_1<=d for
    every clipped x=alpha*r_0+beta*r_1, alpha,beta>=0. It belongs to the
    convex hull of 0, d*r_0/l_0 and d*r_1/l_1 at every instant. Convexity of
    squared norm gives |x|^2<=d^2*max(|r_i|^2/l_i^2). Rotations preserve
    |r_i| exactly. Constant projections are a special case; varying coaxial
    projections use the existing rational Rodrigues remainder bounds.
    A STRICT bound below the shell's inner radius proves empty intersection.
    Tangency, nonpositive lower bounds and unsupported paths retain enclosure.
    """
    from . import integration_differential_geometry as G
    from .integration_regional_inventory import _width
    if constraint.get('kind') != 'moving-ray-edge' or duration <= 0:
        return None
    rays = constraint['rays']
    if len(rays) != 2:
        return None
    if type(layer) is not V.RadialLayer or type(cell) is not V.CartesianCell:
        raise V.VolumeError('radial cap requires the actual physical layer and Cartesian voxel')
    geometry = (*layer._geometry(), *cell._geometry())
    with arena.resource.reserve(8192+64*(_width(rays)+_width(geometry)),
                                category='interface-radial-cap-paths'):
        paths = tuple(_ray_path(ray, G) for ray in rays)
        zero = (Q(0),)*3
        with V._work(geometry, arena.resource, pairs=16):
            arena.work(256)
            inner = layer.bottom_radius_m
            if inner <= 0:
                return None
            inner_squared = inner*inner
            planes = O._box_planes(cell)
        for index, wall in enumerate(planes):
            normal, limit = tuple(Q(q) for q in wall[:3]), Q(wall[3])
            if limit < 0:
                continue
            forms = []
            for path in paths:
                ray, phase, velocity, prior = path
                values = (*normal, limit, *ray, *phase, *velocity,
                          *(q for vector in prior for q in vector), duration)
                with V._work(values, arena.resource, pairs=8):
                    arena.work(128+16*len(prior))
                    form = _generator_form((normal, zero, zero), path, 1, duration)
                    if form is None:
                        break
                    start, moving, _ = form
                    if moving is None:
                        bounds = start, start
                    else:
                        with V._work((start, *moving, duration), arena.resource, pairs=16):
                            arena.work(96)
                            bounds, _ = _departure_bounds(start, moving, duration)
                    if bounds[0] <= 0:
                        break
                    forms.append((form, bounds))
            if len(forms) != 2:
                continue
            lower_bounds = tuple(bounds[0] for _, bounds in forms)
            coefficients = tuple(q for (start, moving, _), bounds in forms
                                 for q in (start, *(moving or ()), *bounds))
            values = (*normal, limit, inner_squared, *coefficients,
                      *(q for path in paths for q in path[0]))
            with V._work(values, arena.resource, pairs=16):
                arena.work(128)
                norms_squared = tuple(O._dot(path[0], path[0]) for path in paths)
                upper = limit*limit*max(norm/(lower*lower)
                    for norm, lower in zip(norms_squared, lower_bounds, strict=True))
                if upper >= inner_squared:
                    continue
                arena.keep((*values, *norms_squared, upper), 64)
                return dict(method='exact-voxel-cap-inside-inner-radius',
                    source_sha256=source_digest(), voxel_plane_index=index,
                    outward_normal=list(map(V._encoded, normal)), wall_limit=V._encoded(limit),
                    generator_constants=[V._encoded(start) if moving is None else None
                                         for (start, moving, _), _ in forms],
                    generator_projection_bounds=[list(map(V._encoded, bounds)) for _, bounds in forms],
                    generator_rodrigues=[None if moving is None else list(map(V._encoded, moving))
                                         for (_, moving, _), _ in forms],
                    generator_norms_squared=list(map(V._encoded, norms_squared)),
                    generator_rules=[rule if moving is None else 'exact-Rodrigues-whole-interval-lower-bound'
                                     for (_, moving, rule), _ in forms],
                    radius_upper_squared=V._encoded(upper), inner_radius_squared=V._encoded(inner_squared),
                    duration_s=V._encoded(duration), open_interval='0 <= t <= duration',
                    area_rule='the actual voxel-capped positive ray cone lies strictly inside the shell hollow core')
    return None


def zero_area(constraint, constraints, literals, duration, arena, *, fixed=()):
    """Certify actual cutting halfspaces; None never authorises zero flux.

    Inputs are the already-issued interface and retained clipping literals.
    ``fixed`` names the measured voxel's walls through the sphere centre as
    (label, inward normal); they clip the same face and move with nothing.
    No material identifier, face name, requested width or measured outcome is
    used to choose a sign. The proof remains valid after any further box,
    radial or neighbour clipping, so no surrogate face area is substituted.
    """
    from . import integration_differential_geometry as G
    from .integration_regional_inventory import _width
    if constraint.get('kind') != 'moving-ray-edge' or duration <= 0:
        return None
    rays = constraint['rays']
    if len(rays) != 2:
        return None
    # Input widths are inspected without serialising/copying the records.
    # This scoped lease covers decoded paths and rational products before
    # actual-operand _work checks; no persistent decoded-path cache is added.
    with arena.resource.reserve(8192+32*_width(rays), category='interface-exclusion-paths'):
        paths = tuple(_ray_path(ray, G) for ray in rays)
        halfspaces = []
        zero = (Q(0),)*3
        candidates = [(name, sign, None) for name, sign in literals]
        candidates += [(label, 1, (tuple(normal), zero, zero)) for label, normal in fixed]
        for name, sign, plane in candidates:
            if sign not in (-1, 1):
                raise V.VolumeError('moving-interface support requires signed halfspaces')
            wall = plane is not None
            cut = None if wall else constraints[name]
            with arena.resource.reserve(8192+32*_width(plane if wall else cut),
                                        category='interface-exclusion-paths'):
                if not wall:
                    plane = G._rigid_plane_path(cut)
                if plane is None or not any(plane[0]):
                    continue
                proofs = tuple(_nonpositive(plane, ray, sign, duration, arena) for ray in paths)
                if any(p is None for p in proofs) or not any(p[0] for p in proofs):
                    halfspaces.append((name, sign, plane, wall))
                    continue
                values = (*(q for row in plane for q in row),
                          *(q for p in proofs for q in p[1]))
                arena.keep(values, 24)
                result = dict(method='exact-coaxial-halfspace-generator-exclusion',
                    source_sha256=source_digest(), constraint_name=name, halfspace_sign=sign,
                    open_interval='0 < t <= duration; t=0 has zero time measure',
                    duration_s=V._encoded(duration),
                    generator_proofs=[dict(strict=p[0], rule=p[2],
                        coefficients=list(map(V._encoded, p[1]))) for p in proofs],
                    area_rule='nonnegative ray cone meets this actual halfspace in at most a line')
                if wall:
                    result.update(halfspace_kind='fixed-voxel-wall-through-sphere-centre',
                                  fixed_inward_normal=list(map(V._encoded, plane[0])))
                return result
        opposite = _opposite_exclusion(halfspaces, paths, duration, arena)
        if opposite is not None:
            return opposite
        # No single halfspace excludes both generators. Two may do so jointly
        # where one generator starts exactly in both of their planes.
        forms = []
        for name, sign, plane, wall in halfspaces:
            operands = tuple(q for row in plane for q in row)
            with V._work((*operands, duration), arena.resource, pairs=8):
                arena.work(64)
                found = tuple(_generator_form(plane, ray, sign, duration) for ray in paths)
            if all(form is not None for form in found):
                forms.append((name, sign, plane, wall, found))
        for shared in (0, 1):
            incident = [row for row in forms if not row[4][shared][0]]
            for first in incident:
                for second in incident:
                    if first is second:
                        continue
                    bounds = _pair_exclusion(first[4], second[4], shared, duration, arena)
                    if bounds is None:
                        continue
                    values = tuple(q for row in (first, second) for d, moving, _ in row[4]
                                   for q in (d, *(moving or ())))
                    arena.keep((*values, *bounds), 32)
                    return dict(method='exact-coaxial-halfspace-pair-generator-exclusion',
                        source_sha256=source_digest(),
                        constraint_names=[first[0], second[0]], halfspace_signs=[first[1], second[1]],
                        fixed_voxel_walls=[first[3], second[3]], shared_generator=shared,
                        open_interval='0 < t <= duration; t=0 has zero time measure',
                        duration_s=V._encoded(duration),
                        generator_forms=[[dict(start=V._encoded(d), rule=rule,
                            rodrigues=None if moving is None else list(map(V._encoded, moving)))
                            for d, moving, rule in row[4]] for row in (first, second)],
                        shared_rate_upper=V._encoded(bounds[0]), other_value_upper=V._encoded(bounds[1]),
                        determinant_rate_lower=V._encoded(bounds[2]),
                        area_rule='nonnegative ray cone meets these two actual halfspaces only on its generator rays')
    return None
