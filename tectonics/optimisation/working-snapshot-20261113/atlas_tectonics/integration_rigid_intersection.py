"""Certified removable moving-plane/fixed-edge quotients, not incidence.

For an initially coincident plane and rectangle edge, both Cramer operands
can contain 2*sin(theta/2). Cancel it algebraically only after exact constant
identities; the reduced denominator must be nonzero on the CLOSED interval.
The caller still proves an actual inside/outside crossing. Unsupported poses,
offsets and singular reduced quotients keep the ordinary geometric fallback.
Two differently rotating rays additionally admit an exact endpoint-series
quotient with outward remainder bounds; their physical plane is not made rigid.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from math import comb, factorial
import hashlib
from pathlib import Path

from . import integration_volume as V, integration_volume_overlap as O

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_SERIES_DEGREE = 32


def source_digest():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise V.VolumeError('rigid intersection source changed after loading')
    return _LOADED


def _ray_intersect(constraint, active, face, bounds, J, arena, *, _line=None):
    """Cancel an EXACT common t in two-ray plane/edge Cramer operands.

    If f(0)=0, f(t)/t=sum(m>=0,f[m+1]*t**m). For rotating rays,
    |f[k]| <= C*W**k/k!, where W is the sum of the angular-vector 1-norms
    and C is the product of ray 1-norms and the edge functional 1-norm.
    After degree N the kth normalised derivative tail is bounded by its
    first majorant term divided by 1-W*R/(N+2-k), R=max(abs(time)).
    This is a convergent-series enclosure, not a truncated approximation.
    No preposed ray or W*R>1 is admitted here; ordinary fallback remains.
    """
    from . import integration_differential_geometry as G
    from . import integration_moving_face_moments as M
    if constraint['kind'] != 'moving-ray-edge':
        return None
    rays = constraint['rays']
    if len(rays) != 2 or any(any(w) and dt for ray in rays
            for w, dt in G._history(ray.get('prior_rotations', ()))):
        return None
    directions = tuple(G._load_vec(ray['direction']) for ray in rays)
    rates = tuple(G._load_vec(ray['angular_velocity_rad_s']) for ray in rays)
    geometric = (*face[:4], *face[4]) if _line is None else _line
    operands = tuple(q for vector in (*directions, *rates, *geometric, bounds) for q in vector)
    # Most regular intersections do not share an exact endpoint factor. Prove
    # eligibility before reserving or constructing the degree32 series.
    with V._work(operands, arena.resource, pairs=32):
        rate = sum(abs(q) for vector in rates for q in vector)
        radius = max(map(abs, bounds))
        if not rate or radius*rate > 1:
            return None
        normal0 = O._cross(*directions)
        candidates = []
        if _line is not None:
            point, direction = _line
            if not any(direction) or O._dot(normal0,direction) or O._dot(normal0,point):
                return None
            candidates.append((None, None, point, direction))
        else:
            for identity in sorted(active, key=repr):
                if not (isinstance(identity, tuple) and len(identity) == 3 and identity[0] == 'rectangle'):
                    continue
                _, fixed, end = identity
                free = 1-fixed
                coordinate = face[4][fixed][end]
                point = tuple(face[0][i]+coordinate*face[fixed+1][i] for i in range(3))
                direction = face[free+1]
                with V._work((*normal0,*point,*direction),arena.resource):
                    if O._dot(normal0,direction) or O._dot(normal0,point):
                        continue
                candidates.append((fixed, coordinate, point, direction))
        if not candidates:
            return None
    N = _SERIES_DEGREE
    # Coefficient denominators divide products of the input denominators and
    # k!. Reserve BEFORE recurrence/convolution growth, including all retained
    # vectors, functionals, tail powers and rational GCD temporaries. Per-value
    # arithmetic checks below retain the actual operand-width admission too.
    count = 16*(N+2)
    bits = 4*(N+2)*(sum(V._bits(q) for q in operands)+(N+2).bit_length())
    with arena.resource.reserve(65536+count*(128+16*((bits+7)//8)),
                                category='ray-quotient-scratch'), V._work(operands, arena.resource):
        arena.work(32*(N+2)**2)
        series = []
        for vector, omega in zip(directions, rates):
            terms = [vector]
            for k in range(1, N+2):
                with V._work((*omega, *terms[-1], k), arena.resource):
                    terms.append(tuple(q/k for q in O._cross(omega, terms[-1])))
            series.append(terms)
        normal = []
        for k in range(N+2):
            with V._work(tuple(q for i in range(k+1) for vector in
                    (series[0][i], series[1][k-i]) for q in vector), arena.resource):
                terms = tuple(O._cross(series[0][i], series[1][k-i]) for i in range(k+1))
                normal.append(tuple(sum(vector[j] for vector in terms) for j in range(3)))
        size = sum(map(abs, directions[0]))*sum(map(abs, directions[1]))

        def quotient(vector):
            arena.work(16*(M.ORDER+1)*(N+1))
            with V._work((*vector, *(q for row in normal for q in row)), arena.resource):
                coefficients = tuple(O._dot(row, vector) for row in normal)
                if coefficients[0] != 0:
                    return None
                C = size*sum(map(abs, vector))
                result = []
                t = (J.I.point(bounds[0])[0], J.I.point(bounds[1])[1])
                for k in range(M.ORDER+1):
                    out = J.zero
                    for m in range(N, k-1, -1):
                        out = J.I.add(J.I.mul(out, t), J.I.point(comb(m, k)*coefficients[m+1]))
                    first = C*rate**(N+2)*radius**(N+1-k)*Q(comb(N+1, k), factorial(N+2))
                    tail = first/(1-radius*rate/Q(N+2-k))
                    result.append(J.I.add(out, (-J.I.point(tail)[1], J.I.point(tail)[1])))
                return tuple(result)

        for fixed, coordinate, point, direction in candidates:
            denominator = quotient(direction)
            numerator = quotient(tuple(-q for q in point))
            if (denominator is None or numerator is None or
                    denominator[0][0] <= 0 <= denominator[0][1]):
                continue
            parameter = J.div(numerator, denominator)
            if fixed is None:
                answer = tuple(J.add(J.constant(p),J.scale(parameter,d))
                               for p,d in zip(point,direction))
            else:
                answer = [None, None]
                answer[fixed] = J.constant(coordinate)
                answer[1-fixed] = parameter
            arena.keep(tuple(Q(q) for coordinate in answer for pair in coordinate for q in pair),
                       len(answer)*(M.ORDER+1))
            return tuple(answer)
    return None


def intersect_world_line(constraint, point, direction, bounds, J, arena):
    """Actual world-coordinate jets on an exact fixed line, or None.

    Solve N(t).(point+s*direction)=0 for the original two-ray normal. Both
    original Cramer constants must vanish EXACTLY at t=0, and the common-t
    quotient denominator must exclude zero on the complete closed interval.
    The existing degree32 majorant bounds every normalised derivative0..12;
    no approximate pole or coincidence test is introduced. The caller owns
    the line's physical origin, its two fixed-plane identities, and the
    already-certified clipping crossing. This helper grants none of those.
    """
    source_digest()
    if (len(point)!=3 or len(direction)!=3 or
            any(not isinstance(q,(int,Q)) for q in (*point,*direction))):
        return None
    return _ray_intersect(constraint, (), None, bounds, J, arena,
                          _line=(tuple(point),tuple(direction)))


def intersect_world_line_reduced(constraint, point, direction, bounds, J, arena):
    """Fixed-line crossing near a genuine pole just outside a leaf t>=a>0.

    With exact p0=N(0).point, d0=N(0).direction and exact series
    N(t).v=v0+t*g_v(t), s=-(p0+t*g_p)/(d0+t*g_d). If tiny nonzero p0/d0
    put the pole near -d0/g_d(0), both operands vary by O(1) relative
    amounts over [a,2a] and their interval quotient cannot certify a sign.
    For t>0, s=-(p0/t+g_p)/(d0/t+g_d) exactly; 1/t has exact monotone
    derivative bounds on [a,b]. Both forms are rigorous and are intersected.
    No constant is snapped, and the pole/zero denominator still declines.
    The g_v tail is the same majorant as _ray_intersect (same f[m+1]).
    """
    from . import integration_differential_geometry as G
    from . import integration_moving_face_moments as M
    source_digest()
    if (len(point)!=3 or len(direction)!=3 or not 0<bounds[0]<=bounds[1] or
            any(not isinstance(q,(int,Q)) for q in (*point,*direction)) or
            constraint['kind']!='moving-ray-edge'):
        return None
    rays=constraint['rays']
    if len(rays)!=2 or any(any(w) and dt for ray in rays
            for w,dt in G._history(ray.get('prior_rotations',()))):
        return None
    directions=tuple(G._load_vec(ray['direction']) for ray in rays)
    rates=tuple(G._load_vec(ray['angular_velocity_rad_s']) for ray in rays)
    point,direction=tuple(map(Q,point)),tuple(map(Q,direction))
    operands=tuple(q for vector in (*directions,*rates,point,direction,bounds) for q in vector)
    with V._work(operands,arena.resource,pairs=32):
        rate=sum(abs(q) for vector in rates for q in vector)
        radius=max(map(abs,bounds))
        normal0=O._cross(*directions)
        constants=O._dot(normal0,point),O._dot(normal0,direction)
        # Exact double zero belongs to the removable endpoint quotient.
        if not rate or radius*rate>1 or not any(direction) or not any(constants):
            return None
    N=_SERIES_DEGREE
    count=16*(N+2)
    bits=4*(N+2)*(sum(V._bits(q) for q in operands)+(N+2).bit_length())
    with arena.resource.reserve(65536+count*(128+16*((bits+7)//8)),
                                category='ray-quotient-scratch'), V._work(operands,arena.resource):
        arena.work(32*(N+2)**2+64*(M.ORDER+1)**2)
        series=[]
        for vector,omega in zip(directions,rates):
            terms=[vector]
            for k in range(1,N+2):
                with V._work((*omega,*terms[-1],k),arena.resource):
                    terms.append(tuple(q/k for q in O._cross(omega,terms[-1])))
            series.append(terms)
        normal=[]
        for k in range(N+2):
            with V._work(tuple(q for i in range(k+1) for vector in
                    (series[0][i],series[1][k-i]) for q in vector),arena.resource):
                terms=tuple(O._cross(series[0][i],series[1][k-i]) for i in range(k+1))
                normal.append(tuple(sum(vector[j] for vector in terms) for j in range(3)))
        size=sum(map(abs,directions[0]))*sum(map(abs,directions[1]))
        t=(J.I.point(bounds[0])[0],J.I.point(bounds[1])[1])

        def reduced(vector):
            # Jets of (f(t)-f(0))/t: the same coefficients f[m+1] and tail
            # majorant as the exact-zero quotient, without requiring f(0)=0.
            arena.work(16*(M.ORDER+1)*(N+1))
            with V._work((*vector,*(q for row in normal for q in row)),arena.resource):
                coefficients=tuple(O._dot(row,vector) for row in normal)
                C=size*sum(map(abs,vector))
                result=[]
                for k in range(M.ORDER+1):
                    out=J.zero
                    for m in range(N,k-1,-1):
                        out=J.I.add(J.I.mul(out,t),J.I.point(comb(m,k)*coefficients[m+1]))
                    first=C*rate**(N+2)*radius**(N+1-k)*Q(comb(N+1,k),factorial(N+2))
                    tail=first/(1-radius*rate/Q(N+2-k))
                    result.append(J.I.add(out,(-J.I.point(tail)[1],J.I.point(tail)[1])))
                return tuple(result)

        p,d=reduced(point),reduced(direction)
        # Exact monotone bounds of the kth Taylor coefficient of 1/t on [a,b].
        inverse=tuple((J.I.point(Q(1,bounds[1]**(k+1)))[0],J.I.point(Q(1,bounds[0]**(k+1)))[1])
                      if k%2==0 else (J.I.point(-Q(1,bounds[0]**(k+1)))[0],J.I.point(-Q(1,bounds[1]**(k+1)))[1])
                      for k in range(M.ORDER+1))
        forms=[]
        denominator=J.add(J.scale(inverse,constants[1]),d)
        if denominator[0][0]>0 or denominator[0][1]<0:
            forms.append(J.div(J.add(J.scale(inverse,constants[0]),p),denominator))
        variable=(t,J.I.point(1))+(J.zero,)*(M.ORDER-1)
        denominator=J.add(J.constant(constants[1]),J.mul(variable,d))
        if denominator[0][0]>0 or denominator[0][1]<0:
            forms.append(J.div(J.add(J.constant(constants[0]),J.mul(variable,p)),denominator))
        if not forms:
            return None
        parameter=forms[0]
        for other in forms[1:]:
            parameter=tuple((max(a,c),min(b,e)) for (a,b),(c,e) in zip(parameter,other))
            if any(lo>hi for lo,hi in parameter):
                raise V.VolumeError('reduced world-line quotient contradicts its direct form')
        answer=tuple(J.sub(J.constant(q),J.scale(parameter,e)) for q,e in zip(point,direction))
        arena.keep(tuple(Q(q) for coordinate in answer for pair in coordinate for q in pair),
                   len(answer)*(M.ORDER+1))
        return answer


def intersect(constraint, active, face, bounds, J, arena):
    """Return analytic local coordinates or None; no ownership/flux authority.

    n(t)=a+b*cos(theta)+c*sin(theta), theta=omega*t. On the fixed
    edge x=p+s*d, solve s=(D+E*cos(theta)+F*sin(theta))/
    (A+B*cos(theta)+C*sin(theta)). A+B=D+E=0 exactly permits
    s=(F*cos(theta/2)-E*sin(theta/2))/(C*cos(theta/2)-B*sin(theta/2)).
    Its endpoint value is the analytic continuation, not a new material point.
    """
    from . import integration_differential_geometry as G
    from . import integration_moving_face_moments as M
    path = G._rigid_plane_path(constraint)
    if path is None:
        return _ray_intersect(constraint, active, face, bounds, J, arena)
    normal, theta, omega = path
    axes = [i for i, q in enumerate(omega) if q]
    # A single Cartesian axis gives an exact rational unit axis and scalar
    # angle. No approximate square root or rounded accumulated pose is used.
    if any(theta) or len(axes) != 1:
        return None
    axis = axes[0]
    operands = (*normal, *theta, *omega, *bounds,
                *(q for vector in face[:4] for q in vector),
                *(q for pair in face[4] for q in pair))
    with V._work(operands, arena.resource):
        unit = tuple(Q(i == axis) for i in range(3))
        parallel = tuple(normal[axis]*q for q in unit)
        perpendicular = tuple(normal[i]-parallel[i] for i in range(3))
        tangent = O._cross(unit, normal)
        for identity in sorted(active, key=repr):
            if not (isinstance(identity, tuple) and len(identity) == 3 and
                    identity[0] == 'rectangle'):
                continue
            _, fixed, end = identity
            free = 1-fixed
            coordinate = face[4][fixed][end]
            point = tuple(face[0][i]+coordinate*face[fixed+1][i] for i in range(3))
            direction = face[free+1]
            A, B, C = (O._dot(v, direction) for v in (parallel, perpendicular, tangent))
            D, E, F = (-O._dot(v, point) for v in (parallel, perpendicular, tangent))
            # _rigid_plane_path admits only homogeneous physical planes.
            # Even a tiny nonzero constant forbids this cancellation.
            if A+B != 0 or D+E != 0:
                continue
            arena.work(128+64*(M.ORDER+1)**2)
            with V._work((*point, *direction, A, B, C, D, E, F), arena.resource), \
                    arena.resource.reserve(131072+4096*(M.ORDER+1), category='rigid-intersection-scratch'):
                basis = tuple((Q(i == (axis+1) % 3),)*2 for i in range(3))
                half = M._rotated(basis, tuple(q/2 for q in omega), bounds, J, arena)
                cosine, sine = half[(axis+1) % 3], half[(axis+2) % 3]
                denominator = J.sub(J.scale(cosine, C), J.scale(sine, B))
                if denominator[0][0] <= 0 <= denominator[0][1]:
                    continue
                numerator = J.sub(J.scale(cosine, F), J.scale(sine, E))
                answer = [None, None]
                answer[fixed] = J.constant(coordinate)
                answer[free] = J.div(numerator, denominator)
                return tuple(answer)
    return None
