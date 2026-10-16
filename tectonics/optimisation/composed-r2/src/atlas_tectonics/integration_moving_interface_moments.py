"""Certified relative flux on a moving two-ray radial interface.

An orthonormal chart preserves the physical annular disks. Actual support and
voxel planes become moving linear cuts; no planar surrogate replaces the
radial boundary. Analytic first moments and Taylor's theorem enclose time.
Unproved chart inverses or clipping topology retain the independent geometric
enclosure and the caller's original precision/leaf limits.
A predicate at the vertex of two actual planes is g/det with g and det entire
in time; their exact Maclaurin prefix plus a rigorous remainder decides its
sign beyond a near-initial pole, or brackets its root. A time leaf is split
at such a certified bracket: each side inherits its proved sign and only the
bracket keeps the geometric kernel. Tiny nonzero values keep their own sign.
A plane lying EXACTLY in the face plane at t=0 has a 0/0 chart line there; on
leaves starting at t=0 it is clipped by the regular line of (n-scale*N)/t.
The second cone line at an authored chart corner, and any line that always
holds a boundary ray of the face, take whole-leaf signs from exact identities.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import hashlib
import heapq
from itertools import combinations
from pathlib import Path

from . import integration_volume as V, integration_volume_overlap as O
from . import integration_moving_face_moments as T
from . import integration_circular_moments as C
from . import integration_rigid_intersection as RI
from .integration_q2_directed import _Branch

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ORDER = T.ORDER


def source_digest():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise V.VolumeError('moving-interface moment source changed after loading')
    return hashlib.sha256((_LOADED+T.source_digest()+C.source_digest()).encode('ascii')).hexdigest()


def _dot(a, b, J):
    value = J.z
    for x, y in zip(a, b):
        value = J.add(value, J.mul(x, y))
    return value


def _ray(ray, bounds, J, arena):
    from . import integration_differential_geometry as D
    vector = tuple((q, q) for q in D._load_vec(ray['direction']))
    for omega, duration in D._history(ray.get('prior_rotations', ())):
        vector = D._rotation_boxes(vector, omega, duration, duration, T.POSE_LEVEL, arena)
    return T._rotated(vector, D._load_vec(ray['angular_velocity_rad_s']), bounds, J, arena)


def _constant_ray_dot(first, second, arena):
    """Recognise an exact common rigid action, including an invariant axis.

    This is an identity on complete paths, not a small dot-product residual.
    Arbitrary unequal prior poses decline; the ordinary interval expression
    remains available for them.
    """
    from . import integration_differential_geometry as D
    rays = (first, second)
    vectors = tuple(D._load_vec(ray['direction']) for ray in rays)
    omegas = tuple(D._load_vec(ray['angular_velocity_rad_s']) for ray in rays)
    histories = tuple(D._history(ray.get('prior_rotations', ())) for ray in rays)
    with V._work(tuple(q for v in (*vectors, *omegas) for q in v), arena.resource):
        arena.work(128)
        if histories[0] == histories[1] and omegas[0] == omegas[1]:
            return O._dot(*vectors)
        if not any(histories) and any(all(w == common or
                not any(O._cross(v, w)) and not any(O._cross(v, common))
                for v, w in zip(vectors, omegas)) for common in omegas):
            return O._dot(*vectors)
    return None


def _rectangle_endpoint(new, face, first_ray, other, axis, coordinate, sign, E, arena):
    """Exact endpoint jets of a positively scaled homogeneous predicate.

    With d=N cross m, the rectangle vertex is A*c*d/(a dot d) for
    u=c, and A*Jc*c*d/((N cross a) dot d) for v=c. Only f/A or
    f/(A*Jc) is claimed rational. Offsets, nonexact prior poses and a zero
    endpoint inverse decline; all physical coordinates remain unchanged.
    """
    if new[1]!=0 or other[1]!=0 or any(lo!=hi for normal,offset in
            (other,new,face,first_ray) for c in normal for lo,hi in c):
        return None
    inputs=tuple(q for normal,offset in (other,new,face,first_ray)
        for q in (offset,*(q for c in normal for pair in c for q in pair)))
    with V._work(inputs,arena.resource,pairs=16*(ORDER+1)**2):
        arena.work(128*(ORDER+1)**3)
        direction=T._cross(face[0],other[0],E)
        normal=first_ray[0] if axis==0 else T._cross(face[0],first_ray[0],E)
        determinant=_dot(normal,direction,E)
        if determinant[0]==E.zero:
            return None
        value=E.scale(E.div(_dot(new[0],direction,E),determinant),sign*coordinate)
        if not all(lo==hi for lo,hi in value):
            return None
        coefficients=tuple(lo for lo,_ in value)
        arena.keep(coefficients,len(coefficients))
        return coefficients,axis


def _scaled_departure(coefficients, value, factor, upper_time, J):
    """Apply the zero-start Taylor sign proof without discarding the factor."""
    if factor[0][0]<=0:
        raise _Branch()
    divided=J.div(value,factor)
    departure,open_sign=T._endpoint_departure(coefficients,divided,upper_time,J)
    return (None if departure is None else J.I.mul(departure,factor[0])),open_sign


def _initial_value_enclosure(coefficients, value, factor, upper_time, J):
    """Exact NONZERO t=0 value plus Taylor's theorem on the closed [0,T].

    f(t)=sum(k<d,c[k]*t**k)+f^(d)(xi)/d!*t**d, xi in [0,t]. Nested
    evaluation over t in [0,T] keeps the exact c[k] and the leaf's own
    f^(d)/d! enclosure, so a positive slope may dominate a small opposite
    curvature. Every order is rigorous; all are intersected. A sign is
    issued only if this closed enclosure excludes zero; c[0] is never
    rounded to zero and a zero start is left to the endpoint-departure rule.
    """
    if factor[0][0]<=0:
        raise _Branch()
    divided=J.div(value,factor)
    span=(J.I.point(0)[0],J.I.point(upper_time)[1])
    exact=tuple(J.I.point(q) for q in coefficients)
    bound=None
    for degree in range(1,ORDER+1):
        nested=divided[degree]
        for k in range(degree-1,-1,-1):
            nested=J.I.add(exact[k],J.I.mul(span,nested))
        bound=nested if bound is None else (max(bound[0],nested[0]),min(bound[1],nested[1]))
    if bound[0]>bound[1]:
        raise V.VolumeError('moving-interface initial-value Taylor bound contradicts physical jets')
    sign=True if bound[0]>0 else False if bound[1]<0 else None
    return J.I.mul(bound,factor[0]),sign


def _taylor_point(reference, value, offset, J):
    """f(m+offset) by Taylor's theorem about an expansion point m.

    ``reference`` holds the normalised derivatives 0..ORDER-1 AT m and
    ``value[ORDER]`` encloses f^(ORDER)/ORDER! on a time set containing m
    and m+offset, so the Lagrange form is exact. Nothing is truncated.
    """
    step=J.I.point(offset)
    result=value[ORDER]
    for k in range(ORDER-1,-1,-1):
        result=J.I.add(reference[k],J.I.mul(result,step))
    return result


def _taylor_range(reference, value, lower, upper, J):
    """Enclose f(m+s) for every offset s in [lower,upper] (interval Horner)."""
    span=(J.I.point(lower)[0],J.I.point(upper)[1])
    result=value[ORDER]
    for k in range(ORDER-1,-1,-1):
        result=J.I.add(reference[k],J.I.mul(result,span))
    return result


def _taylor_slope(reference, value, lower, upper, J):
    """f' for offsets in [lower,upper] from the SAME model, one order lower.

    f'(m+s)=sum(k<ORDER,k*f_k(m)*s**(k-1))+ORDER*f_ORDER(xi)*s**(ORDER-1):
    Taylor's theorem applied to f' itself, whose order ORDER-1 normalised
    derivative is ORDER*f_ORDER. The caller may intersect a direct jet.
    """
    span=(J.I.point(lower)[0],J.I.point(upper)[1])
    result=J.I.mul(J.I.point(ORDER),value[ORDER])
    for k in range(ORDER-1,0,-1):
        result=J.I.add(J.I.mul(J.I.point(k),reference[k]),J.I.mul(result,span))
    return result


def _monotone_event(reference, value, slope, lower, upper, J, steps=80):
    """Bracket the single root of a strictly monotone predicate on a leaf.

    ``slope`` must exclude zero for all offsets in [lower,upper]. Both ends
    need certified strictly opposite signs; every accepted probe has a
    certified strict sign, so by monotonicity the predicate keeps the first
    sign up to ``lo`` and the second from ``hi``. Returns offsets
    (lo,hi,first_sign), or None when no such strict proof exists.
    """
    if slope[0]<=0<=slope[1]:
        return None
    def sign(offset):
        bound=_taylor_point(reference,value,offset,J)
        return True if bound[0]>0 else False if bound[1]<0 else None
    lo,hi=lower,upper
    before,after=sign(lo),sign(hi)
    if before is None or after is None or before==after:
        return None
    for _ in range(steps):
        middle=(lo+hi)/2
        probes=(middle,)
        if sign(middle) is None:
            # The enclosure cannot separate this point from the root; close
            # in from both sides, never guessing the unresolved sign.
            probes=((lo+middle)/2,(middle+hi)/2)
        moved=False
        for probe in probes:
            found=sign(probe)
            if found is before and probe>lo:
                lo,moved=probe,True
            elif found is after and probe<hi:
                hi,moved=probe,True
        if not moved:
            break
    return lo,hi,before


def _start_event(coefficients, divided, upper, J):
    """Sign or first-root bracket on (0,upper] from the EXACT Maclaurin prefix.

    With c=coefficients[m] the first nonzero exact coefficient,
    f(t)=t**m*(c+t*psi(t)), psi(t)=sum(m<k<ORDER,c_k*t**(k-m-1))
    +f_ORDER(xi)*t**(ORDER-m-1), and ``divided[ORDER]`` encloses f_ORDER on
    [0,upper]. While t*max|psi|<|c| the sign is that of c. Where psi has the
    strictly opposite sign, t*min|psi|>|c| proves the reversed sign, and
    every root satisfies t=|c|/|psi(t)|. No coefficient is rounded to zero.
    Returns ('sign',s), ('event',first,last,s,after) with exact rational
    bracket ends (after is None where the leaf end is not proved), or None.
    """
    m=next((k for k in range(ORDER) if coefficients[k]),None)
    if m is None:
        return None
    constant=coefficients[m];positive=constant>0;size=abs(Q(constant))
    def psi(lower,higher):
        span=(J.I.point(lower)[0],J.I.point(higher)[1])
        result=divided[ORDER]
        for k in range(ORDER-1,m,-1):
            result=J.I.add(J.I.point(coefficients[k]),J.I.mul(result,span))
        return result
    def opposite(bound):
        return bound[1]<0 if positive else bound[0]>0
    bound=psi(0,upper)
    if bound[0]>=0 if positive else bound[1]<=0:
        return 'sign',positive
    first=size/max(abs(Q(bound[0])),abs(Q(bound[1])))
    if first>upper:
        return 'sign',positive
    if not opposite(bound):
        return 'event',first,upper,positive,None
    last=size/min(abs(Q(bound[0])),abs(Q(bound[1])))
    for _ in range(8):
        end=min(last,upper)
        if first>=end:
            break
        bound=psi(first,end)
        if not opposite(bound):
            break
        lower=size/max(abs(Q(bound[0])),abs(Q(bound[1])))
        higher=size/min(abs(Q(bound[0])),abs(Q(bound[1])))
        if lower>end:
            if end==upper:
                return 'sign',positive
            raise V.VolumeError('moving-interface start-event bounds contradict')
        tightened=max(first,lower),min(last,higher)
        if tightened[0]>tightened[1]:
            # Strict sign(c) below and strict reversal above cannot abut.
            raise V.VolumeError('moving-interface start-event bounds contradict')
        if tightened==(first,last):
            break
        first,last=tightened
    return ('event',first,last,positive,not positive) if last<upper else ('event',first,upper,positive,None)


def _event_grid(first, last, lower, upper):
    """Dyadic split times strictly outside a rational root bracket.

    Bounded bit growth only; the returned part [down,up] is never narrower
    than the certified bracket. ``down`` is None unless it exceeds ``lower``.
    """
    scale=max((last-first)/2,(upper-lower)/2**160)
    ratio=1/scale
    bits=(ratio.numerator//ratio.denominator).bit_length()
    scaled=first*2**bits
    down=Q(-(-scaled.numerator//scaled.denominator)-1,2**bits)
    scaled=last*2**bits
    up=Q(scaled.numerator//scaled.denominator+1,2**bits)
    return (down if down>lower else None),min(up,upper)


def _same_initial_plane(new, face, arena):
    """Exact homogeneous plane identity, independent of the vertex chart.

    A signed proportional normal has the same zero set. This proves only the
    initial predicate value, never its later sign or an all-time incidence.
    Tiny offsets/nonparallel components and degenerate normals do not qualify.
    """
    if new[1]!=0 or face[1]!=0 or not any(new[0]) or not any(face[0]):
        return False
    with V._work((*new[0],*face[0]),arena.resource):
        arena.work(32)
        return not any(O._cross(new[0],face[0]))


def _initial_edge_contains(new, face, other, arena):
    """Exact affine line containment at t=0, including actual offsets.

    On N.x=0 and a.x=da, n.x=dn holds iff n is in span(N,a)
    and its coefficient of a times da equals dn. A nonzero cross-product
    component proves the required independent normals without division.
    """
    if face[1]!=0:
        return False
    with V._work((*new[0],new[1],*face[0],*other[0],other[1]),arena.resource,pairs=8):
        arena.work(64)
        direction=O._cross(other[0],face[0])
        if not any(direction) or O._dot(new[0],direction)!=0:
            return False
        j=next(i for i,q in enumerate(direction) if q)
        return new[1]*direction[j]==other[1]*O._cross(new[0],face[0])[j]


def _fixed_world_line(one, two, arena):
    """Actual intersection line of two independent affine voxel planes."""
    with V._work((*one[0],one[1],*two[0],two[1]),arena.resource,pairs=16):
        arena.work(96)
        direction=O._cross(one[0],two[0]);square=O._dot(direction,direction)
        if not square:
            return None
        left,right=O._cross(two[0],direction),O._cross(direction,one[0])
        point=tuple((one[1]*x+two[1]*y)/square for x,y in zip(left,right))
        arena.keep((*point,*direction),3)
        return point,direction


def _physical_plane_key(constraint,arena):
    """Exact unoriented physical plane/action, for incidence ONLY."""
    from . import integration_differential_geometry as D
    from . import integration_regional_inventory as R
    with arena.resource.reserve(4096+16*R._width(constraint),category='moving-interface-plane-identity'):
        path=D._rigid_plane_path(constraint)
        if path is None:
            return None
        with V._work(tuple(q for vector in path for q in vector),arena.resource,pairs=16):
            arena.work(64)
            key=D._plane_identity(constraint)[0]
            arena.keep(tuple(q for vector in key for q in vector),4)
            return key


def _common_plane_factor(new, other, first, second, fixed, arena):
    """Exact nonzero determinant factor, not a zero/incidence declaration.

    n,m must share either ray's current rigid action with no unapplied prior
    pose; the other ray may have a different commuting rate. Histories and
    offset n/m planes decline. At m.x=0, q.x=d, (a cross b).x=0,
    n.x = d*p.R((wb-wa)t)b0 / (q.(m cross (a cross b))),
    p=(n0.a0)m0-(m0.a0)n0. Every tiny component of p is retained.
    For common action with b instead, p=(m0.b0)n0-(n0.b0)m0 and
    the relative vector is R((wa-wb)t)a0; N=a cross b is NOT reversed.
    If instead both rays share one action wf and n,m share a commuting wn,
    n.(m cross N)=(n cross m).N is rotation invariant: p=n0 cross m0 and
    the relative vector is R((wf-wn)t)(a0 cross b0). This exact small cross
    product keeps nearly coincident fixed cuts' tiny nonzero predicate.
    ``fixed=None`` issues only this common-action numerator identity; the
    caller must supply its actual moving section denominator and scale.
    """
    from . import integration_differential_geometry as D
    from . import integration_regional_inventory as R
    with arena.resource.reserve(4096+16*R._width((new,other,first,second)),
                                category='moving-interface-factor-inputs'):
        one,two=D._rigid_plane_path(new),D._rigid_plane_path(other)
        if one is None or two is None or any(one[1]) or any(two[1]) or any(
                D._history(ray.get('prior_rotations',())) for ray in (first,second)):
            return None
        n,_,wn=one;m,_,wm=two
        a,b=(D._load_vec(ray['direction']) for ray in (first,second))
        wa,wb=(D._load_vec(ray['angular_velocity_rad_s']) for ray in (first,second))
        q,d=fixed if fixed is not None else ((Q(0),)*3,Q(1))
        inputs=tuple(x for vector in (n,m,a,b,wn,wm,wa,wb,q) for x in vector)+(d,)
        with V._work(inputs,arena.resource,pairs=16):
            arena.work(128)
            if wn!=wm or any(O._cross(wa,wb)) or fixed is not None and not any(q):
                return None
            if wn==wa:
                na,ma=O._dot(n,a),O._dot(m,a)
                p=tuple(na*x-ma*y for x,y in zip(m,n))
                vector=b;delta=tuple(x-y for x,y in zip(wb,wa))
            elif wn==wb:
                nb,mb=O._dot(n,b),O._dot(m,b)
                p=tuple(mb*x-nb*y for x,y in zip(n,m))
                vector=a;delta=tuple(x-y for x,y in zip(wa,wb))
            elif wa==wb and not any(O._cross(wn,wa)):
                p=O._cross(n,m)
                vector=O._cross(a,b);delta=tuple(x-y for x,y in zip(wa,wn))
            else:
                return None
            result=p,vector,delta,d
            arena.keep((*p,*vector,*delta,d),5)
            return result


def _factored_predicate(factor, denominator, bounds, sign, J, arena, *, section_scale=None):
    """Rearrange the full predicate jets with a closed actual denominator."""
    if denominator[0][0]<=0<=denominator[0][1]:
        raise _Branch()
    p,b,delta,d=factor
    with arena.resource.reserve(65536,category='moving-interface-factor-jets'):
        arena.work(96*(ORDER+1)**2)
        relative=T._rotated(tuple((q,q) for q in b),delta,bounds,J,arena)
        numerator=_dot(tuple(J.constant(q) for q in p),relative,J)
        result=J.scale(J.div(numerator,denominator),sign*d)
        return result if section_scale is None else J.mul(result,section_scale)


def _intersect_predicate(value, rearranged):
    result=tuple((max(a,c),min(b,d)) for (a,b),(c,d) in zip(value,rearranged))
    if any(lo>hi for lo,hi in result):
        raise V.VolumeError('moving-interface predicate rearrangement contradicts physical jets')
    return result


def _axial_flow_ray(ray, omega, arena):
    """A face ray on the material axis and fixed by its own motion.

    d x w_ray=0, every prior rotation axis parallel to d and d x omega=0,
    all exact: material and face then move every point of that ray alike
    (not at all), so the relative flux numerator vanishes on its whole line.
    This is incidence of the actual zero-flow line, never a small-flux test.
    """
    from . import integration_differential_geometry as D
    direction=D._load_vec(ray['direction']);rate=D._load_vec(ray['angular_velocity_rad_s'])
    history=tuple(w for w,dt in D._history(ray.get('prior_rotations',())) if dt and any(w))
    with V._work((*direction,*rate,*omega,*(q for w in history for q in w)),arena.resource):
        arena.work(32*(len(history)+2))
        return any(direction) and all(not any(O._cross(direction,w)) for w in (*history,rate,omega))


def _cone_corner_inside(first, second, u, v, arena):
    """Whole-time weak sign of the second cone line at a fixed chart point.

    With G=a.b and C=|a|^2|b|^2 (rotations keep both norms), the chart
    predicate is (u*sqrt(C-G^2)-v*G)/|a|. For u,v>=0 not both zero it is
    nonnegative iff G<=0 or (u^2+v^2)*G^2<=u^2*C, i.e. G<=sqrt(H) with
    H=u^2*C/(u^2+v^2). Rates about one common axis w give
    G(t)=B+(perpendicular parts' dot), B=(a.w)(b.w)/(w.w), whose second term
    is bounded by sqrt(K), K the product of the squared perpendicular norms
    (Cauchy-Schwarz); equal rates keep G=G(0) exactly. B+sqrt(K)<=sqrt(H)
    is decided in exact rationals, including equality: a corner exactly ON
    the cone line at an instant stays weakly inside, while any exact deficit,
    however tiny, is refused. True certifies inside for ALL time; False only
    declines (other quadrants, prior poses, noncommuting rates, zero rays).
    """
    from . import integration_differential_geometry as D
    if any(D._history(ray.get('prior_rotations',())) for ray in (first,second)):
        return False
    a,b=(D._load_vec(ray['direction']) for ray in (first,second))
    wa,wb=(D._load_vec(ray['angular_velocity_rad_s']) for ray in (first,second))
    with V._work((u,v,*a,*b,*wa,*wb),arena.resource,pairs=16):
        arena.work(128)
        aa,bb=O._dot(a,a),O._dot(b,b)
        if u<0 or v<0 or not (u or v) or not aa or not bb or any(O._cross(wa,wb)):
            return False
        H=u*u*aa*bb/(u*u+v*v)
        if wa==wb:
            # One rigid action: the Gram entry itself is invariant.
            G=O._dot(a,b)
            return G<=0 or G*G<=H
        w=wa if any(wa) else wb
        ww=O._dot(w,w);aw,bw=O._dot(a,w),O._dot(b,w)
        B=aw*bw/ww;K=(aa-aw*aw/ww)*(bb-bw*bw/ww)
        if B<=0 and K<=B*B:
            return True
        # (B+sqrt(K))^2<=H  <=>  2*B*sqrt(K)<=L, squared with its sign.
        L=H-B*B-K
        return (L>=0 and 4*B*B*K<=L*L) if B>=0 else (L>=0 or 4*B*B*K>=L*L)


def _coincident_start(constraint, face, arena):
    """(scale,n0,rate) with n(0)=scale*N(0) EXACTLY, or None.

    Such a homogeneous plane meets the moving face in the line d(t).x=0,
    d=n-scale*N, d(0)=0. For t>0 that is the line of D=d/t, a positive
    rescaling with the regular limit D(0)=d'(0): the same half-plane without
    the 0/0 chart line. Only an exact point pose turning at one rate
    qualifies; offsets, prior poses, deforming edges and a merely nearly
    parallel start keep their own (possibly tiny, nonzero) line.
    """
    from . import integration_differential_geometry as D
    if face is None:
        return None
    path=D._rigid_plane_path(constraint)
    if path is None or any(path[1]) or not _same_initial_plane((path[0],Q(0)),face,arena):
        return None
    with V._work((*path[0],*path[2],*face[0]),arena.resource):
        arena.work(64)
        result=O._dot(path[0],face[0])/O._dot(face[0],face[0]),path[0],path[2]
    arena.keep((result[0],*result[1],*result[2]),1)
    return result


def _reduced_normal(found, normal, face, rates, bounds, cache, J, arena):
    """Jets of D=(n-scale*N)/t on a leaf that starts at t=0.

    ``normal`` (the plane's own n) and ``face`` (rays a, b and N=a cross b)
    hold jets on ``bounds``: the start leaf [0,b], or one time m>0 (its
    midpoint), where D is the exact jet quotient by t. On the leaf,
    D(t)=integral(0,1) d'(s*t) ds, hence
    D_k(t)=integral (k+1)*s**k*d_(k+1)(s*t) ds: a weighted mean over [0,t]
    of d_(k+1)=(d')_k/(k+1). The jets of d' on [0,b] therefore enclose every
    normalised derivative of D on the leaf, t=0 included, with
    d'=rate x n-scale*((wa x a) x b+a x (wb x b)). A leaf starting later has
    no 0/0 line and is refused here, not approximated.
    """
    scale,start,rate=found
    if bounds[0]!=0 and bounds[0]!=bounds[1]:
        raise V.VolumeError('a reduced interface line needs a leaf starting at the initial time')
    with arena.resource.reserve(65536+8192*(ORDER+1),category='moving-interface-reduced-line'):
        arena.work(32*(ORDER+1)**2)
        if bounds[0]>0:
            difference=tuple(J.sub(x,J.scale(y,scale)) for x,y in zip(normal,face['normal']))
            time=(J.I.point(bounds[0]),J.I.point(1))+(J.zero,)*(ORDER-1)
            return tuple(J.div(x,time) for x in difference)
        if 'rate' not in cache:
            arena.work(192*(ORDER+1)**2)
            wa,wb=(tuple(J.constant(q) for q in w) for w in rates)
            a,b=face['a'],face['b']
            cache['rate']=tuple(J.add(x,y) for x,y in zip(
                T._cross(T._cross(wa,a,J),b,J),T._cross(a,T._cross(wb,b,J),J)))
        own=(J.z,)*3
        if any(rate):
            own=T._cross(tuple(J.constant(q) for q in rate),normal,J)
        derivative=tuple(J.sub(x,J.scale(y,scale)) for x,y in zip(own,cache['rate']))
        return tuple(tuple(J.I.mul(c[k],J.I.point(Q(1,k+1))) for k in range(ORDER+1)) for c in derivative)


def _reduced_prefix(exact):
    """Exact Maclaurin prefix of a REDUCED predicate f/t, or None.

    With f/factor=sum(c[k]*t**k) exact, (f/t)/factor=sum(c[k+1]*t**k). That
    needs c[0]=0, the vertex's finite start pose in the common plane; the
    reduced predicate then STARTS at c[1], which may be zero or not. The
    unshifted prefix would report every such start as zero.
    """
    if exact is None or exact[0][0]!=0:
        return None
    return exact[0][1:],exact[1]


def _reduced_zero_start(exact):
    """True only where a reduced predicate's EXACT start value c[1] is zero."""
    prefix=_reduced_prefix(exact)
    return prefix is not None and prefix[0][0]==0


def _authored_corner(point, active, rectangle, J):
    """Exact chart coordinates of an authored rectangle corner, else None.

    Both edge identities, one per axis, AND the vertex's own constant jets
    are required: an identity alone or a nearby vertex does not qualify.
    """
    edges=[edge for edge in active if isinstance(edge,tuple) and edge[0]=='rectangle']
    if len(edges)!=2 or {edge[1] for edge in edges}!={0,1}:
        return None
    ends={edge[1]:edge[2] for edge in edges}
    corner=rectangle[0][ends[0]],rectangle[1][ends[1]]
    return corner if tuple(point[:2])==tuple(J.constant(q) for q in corner) else None


def _ray_line_sign(line, cone, point, index, weak_inside, J):
    """Sign at ``point`` of a line that vanishes along interface ray ``index``.

    A homogeneous chart line containing that ray is kappa(t) times the ray's
    cone line, exactly: (0,kappa) for the first ray, kappa*(b2,-b1) with b2>0
    for the second. A closed nonzero coefficient fixes sign(kappa) on the
    leaf; the vertex's own cone value (strict, else the caller's weak
    whole-time bound) fixes the rest. No proximity and no sampled sign:
    an offset line, an ambiguous kappa or an undecided cone value decline.
    """
    if line[2]!=J.z:
        return None
    if index==0:
        factor=line[1][0]
        value=point[1][0]
    else:
        factor=line[0][0]
        if factor[0]<=0<=factor[1] and (cone[1][0][0]>0 or cone[1][0][1]<0):
            # kappa=c2/(-b1) wherever -b1 is closed nonzero.
            factor=J.I.mul(line[1][0],cone[1][0])
        value=J.add(J.mul(cone[0],point[0]),J.mul(cone[1],point[1]))[0]
    if factor[0]<=0<=factor[1]:
        return None
    inside=True if value[0]>0 else False if value[1]<0 else True if weak_inside else None
    if inside is None:
        return None
    return inside if factor[0]>0 else not inside


def _initial_flow_plane(first,second,omega,arena):
    """Exact t=0 numerator plane of flux P.x/|a cross b|^3.

    It supplies only zero-set authority. The actual signed velocity jets and
    their derivatives remain the operands of every later classification.
    Non-point prior poses and a degenerate interface decline, not round.
    """
    from . import integration_differential_geometry as D
    posed=[]
    for ray in (first,second):
        vector,_,interval=D._ray_box(D._load_vec(ray['direction']),D._load_vec(ray['angular_velocity_rad_s']),
            Q(0),Q(0),T.POSE_LEVEL,arena,D._history(ray.get('prior_rotations',())))
        if any(lo!=hi for lo,hi in interval):
            return None
        posed.append(vector)
    rates=tuple(D._load_vec(ray['angular_velocity_rad_s']) for ray in (first,second))
    with V._work(tuple(q for vector in (*posed,*rates,omega) for q in vector),arena.resource,pairs=32):
        arena.work(128)
        a,b=posed;normal=O._cross(a,b)
        if not any(normal):
            return None
        ca,cb=(O._dot(O._cross(tuple(x-y for x,y in zip(omega,rate)),vector),normal)
            for rate,vector in zip(rates,posed))
        result=tuple(ca*x+cb*y for x,y in zip(O._cross(b,normal),O._cross(normal,a)))
        arena.keep(result,1)
        return result,Q(0)


def _chart(first, second, omega, outward_sign, bounds, J, arena):
    """x=u*e1+v*e2; return the true cone and relative normal-flux coefficients.

    dA=Jc*dalpha*dbeta, alpha=(u-b1*v/b2)/A, beta=v/b2.
    Thus (ca*alpha+cb*beta)/Jc = cu*u+cv*v, with b2=Jc/A.
    All square roots and reciprocals require a closed positive enclosure.
    """
    from . import integration_differential_geometry as D
    a, b = (_ray(ray, bounds, J, arena) for ray in (first, second))
    original = D._load_vec(first['direction'])
    A = C._sqrt(J.constant(O._dot(original, original)), J)
    normal = T._cross(a, b, J)
    invariant_dot = _constant_ray_dot(first, second, arena)
    if invariant_dot is None:
        Jc = C._sqrt(_dot(normal, normal, J), J)
    else:
        other = D._load_vec(second['direction'])
        Jc = C._sqrt(J.constant(O._dot(original, original)*O._dot(other, other)-invariant_dot**2), J)
    e1 = tuple(J.div(x, A) for x in a)
    e3 = tuple(J.div(x, Jc) for x in normal)
    e2 = T._cross(e3, e1, J)
    b1 = _dot(b, e1, J) if invariant_dot is None else J.div(J.constant(invariant_dot), A)
    b2 = J.div(Jc, A)
    coefficients = []
    for ray, vector in ((first, a), (second, b)):
        relative = tuple(J.constant(x-y) for x, y in zip(omega, D._load_vec(ray['angular_velocity_rad_s'])))
        coefficients.append(_dot(T._cross(relative, vector, J), normal, J))
    ca, cb = coefficients
    cu = J.div(ca, J.mul(A, Jc))
    cv = J.div(J.sub(J.mul(A, cb), J.mul(ca, b1)), J.mul(Jc, Jc))
    return e1, e2, (b2, J.neg(b1), J.z), tuple(J.scale(x, outward_sign) for x in (cu, cv)), (A,Jc)


def integrate(*, layer, cell, first, second, outward_sign, omega, constraints,
              literals, duration, widths, max_leaves, fallback, arena):
    """Enclose both directed physical streams, falling back on each time leaf.

    ``fallback(t0,t1,level)`` must enclose the SAME complete two-ray face, all
    actual cuts and voxel, not a numerical or already closed FV allocation.
    No result is accepted unless both original stream-width limits hold.
    """
    source_digest()
    from . import integration_differential_geometry as D
    from . import integration_regional_inventory as R
    from . import integration_wall_measures as W
    J = T._Jets()
    radius = layer.top_radius_m
    rectangle = ((-radius, radius),)*2
    planes = len(literals)+8
    # Charge decoded input paths, two simultaneous coefficient passes, linear
    # predicates and queue containers; scalar arithmetic also charges work.
    encoded_width = R._width((first, second, constraints, literals))
    scratch = 131072+32*encoded_width+8192*(planes+8)*(ORDER+1)+512*(planes+4)**2
    with arena.resource.reserve(scratch, category='moving-interface-Taylor-scratch'):
        arena.work(128+64*(planes+4)**2)
        # Equal actual literals are one physical cut. Do not infer equality
        # from parallelism, close coefficients or matching sampled normals.
        cuts = []
        for name, sign in literals:
            if not any(sign == s and constraints[name] == item for _, s, item in cuts):
                cuts.append((name, sign, constraints[name]))
        physical_plane_keys={name:_physical_plane_key(item,arena) for name,_,item in cuts}
        fixed = tuple((tuple(-q for q in p[:3]), -p[3]) for p in O._box_planes(cell)
            if not (p[3] >= 0 and p[3]*p[3] >= radius*radius*O._dot(p[:3], p[:3])))
        path_record = {'constraints': {name: item for name, _, item in cuts}}
        for i, (normal, offset) in enumerate(fixed):
            path_record['constraints'][('voxel', i)] = dict(kind='fixed-plane',
                normal=D._store_vec(normal), offset=D._qtext(offset))
            physical_plane_keys[('voxel',i)]=_physical_plane_key(path_record['constraints'][('voxel',i)],arena)
        for i, ray in enumerate((first, second)):
            # These records supply ray identity ONLY. Actual nondegenerate
            # cone lines below, not their zero cross products, prove incidence.
            path_record['constraints'][('cone', i)] = dict(kind='moving-ray-edge',rays=(ray,ray))
        ray_paths = T._shared_ray_paths(path_record, arena=arena)
        # A stationary interface ray d stays in a homogeneous rigid cut whose
        # every rotation is about d iff n0.d=0 EXACTLY; otherwise that cut's
        # value along d keeps the exact sign of n0.d (see axial_sign).
        axial_rays = {}
        for i, ray in enumerate((first, second)):
            for path in ray_paths[('cone', i)]:
                if not path[1] and not any(path[2]):
                    # The ACTUAL authored direction keeps its orientation.
                    axial_rays[i] = path, D._load_vec(ray['direction'])
        axial_planes = {}
        for name, constraint in path_record['constraints'].items():
            if not axial_rays or isinstance(name, tuple) and name[0] == 'cone':
                continue
            plane = D._rigid_plane_path(constraint)
            if plane is None:
                continue
            normal, theta, rate = plane
            for i, (path, direction) in axial_rays.items():
                with V._work((*normal, *theta, *rate, *direction), arena.resource):
                    arena.work(32)
                    if any(O._cross(theta, direction)) or any(O._cross(rate, direction)):
                        continue
                    product = O._dot(normal, direction)
                arena.keep((product,), 1)
                axial_planes[name, i] = product
                if product == 0:
                    ray_paths[name] = ray_paths.get(name, frozenset()) | {path}
        interface_paths = ray_paths[('cone', 0)] | ray_paths[('cone', 1)]
        for sign in (-1, 1):
            ray_paths[('flow', sign)] = frozenset().union(*(ray_paths[('cone', i)]
                for i, ray in enumerate((first, second)) if D._load_vec(ray['angular_velocity_rad_s']) == omega
                or _axial_flow_ray(ray, omega, arena)))
        start_planes, start_cache, factor_cache, fixed_lines = {}, {}, {}, {}
        corner_cache, reduced_cache = {}, {}
        ray_rates = tuple(D._load_vec(ray['angular_velocity_rad_s']) for ray in (first, second))
        exact_jets, endpoint_coefficients = {}, {}
        E=T._Jets(T._RationalIntervals(), budget=arena.resource)
        def world_jet(name):
            if name in exact_jets:
                return exact_jets[name]
            result=None
            if name==('interface',):
                result=T._normal(dict(kind='moving-ray-edge',rays=(first,second)),(Q(0),Q(0)),E,arena)
            elif isinstance(name,tuple) and name[0]=='ray':
                result=_ray((first,second)[name[1]],(Q(0),Q(0)),E,arena),Q(0)
            elif isinstance(name,tuple) and name[0]=='cone':
                face=world_jet(('interface',))
                if face is not None:
                    vector=_ray((first,second)[name[1]],(Q(0),Q(0)),E,arena)
                    result=T._cross(face[0],vector,E),Q(0)
            elif name in path_record['constraints']:
                result=T._normal(path_record['constraints'][name],(Q(0),Q(0)),E,arena)
            if result is not None:
                values=tuple(q for coordinate in result[0] for pair in coordinate for q in pair)
                if any(lo!=hi for coordinate in result[0] for lo,hi in coordinate):
                    result=None
                else:
                    arena.keep((*values,result[1]),3*(ORDER+1)+3)
            exact_jets[name]=result
            return result
        def exact_coefficients(name,active):
            # The world predicate must have exactly the chart line's scale.
            # Cone/flow cuts use a different normalisation, so decline here.
            if name not in {n for n,_,_ in cuts} and not (isinstance(name,tuple) and name[0]=='voxel'):
                return None
            key=name,active
            if key in endpoint_coefficients:
                return endpoint_coefficients[key]
            new,face=world_jet(name),world_jet(('interface',))
            result=None
            if new is not None and face is not None:
                for one,two in combinations(sorted(active,key=repr),2):
                    a,b=world_jet(one),world_jet(two)
                    if a is None or b is None:
                        rectangle_edge=next((edge for edge in (one,two) if
                            isinstance(edge,tuple) and edge[0]=='rectangle'),None)
                        other=b if rectangle_edge==one else a
                        if rectangle_edge is None or other is None or other[1]!=0 or new[1]!=0:
                            continue
                        first_ray=world_jet(('ray',0))
                        if first_ray is None:
                            continue
                        axis,end=rectangle_edge[1:]
                        sign=next((s for n,s,_ in cuts if n==name),1)
                        result=_rectangle_endpoint(new,face,first_ray,other,axis,
                            rectangle[axis][end],sign,E,arena)
                        if result is not None:
                            break
                        continue
                    inputs=tuple(q for normal,offset in (a,b,new,face)
                        for q in (offset,*(q for c in normal for pair in c for q in pair)))
                    with V._work(inputs,arena.resource,pairs=16*(ORDER+1)**2):
                        arena.work(128*(ORDER+1)**3)
                        bn,na=T._cross(b[0],face[0],E),T._cross(face[0],a[0],E)
                        determinant=_dot(a[0],bn,E)
                        if determinant[0]==E.zero:
                            continue
                        point=tuple(E.div(E.add(E.scale(x,a[1]),E.scale(y,b[1])),determinant)
                            for x,y in zip(bn,na))
                        sign=next((s for n,s,_ in cuts if n==name),1)
                        evaluated=E.scale(E.sub(_dot(new[0],point,E),E.constant(new[1])),sign)
                        if all(lo==hi for lo,hi in evaluated):
                            coefficients=tuple(lo for lo,_ in evaluated)
                            arena.keep(coefficients,len(coefficients))
                            result=coefficients,None
                        break
            endpoint_coefficients[key]=result
            return result
        numerator_cache={}
        def numerator_exact(name,active):
            # f=g/det at the vertex of two actual planes on the moving face:
            # g and det are ENTIRE in time (rotations only), so their exact
            # Maclaurin prefix stays useful beyond a near-initial pole of f.
            if name not in {n for n,_,_ in cuts} and not (isinstance(name,tuple) and name[0]=='voxel'):
                return None
            key=name,active
            if key in numerator_cache:
                return numerator_cache[key]
            new,face=world_jet(name),world_jet(('interface',))
            result=None
            if new is not None and face is not None:
                sign=next((s for n,s,_ in cuts if n==name),1)
                for one,two in combinations(sorted(active,key=repr),2):
                    a,b=world_jet(one),world_jet(two)
                    if a is None or b is None:
                        continue
                    inputs=tuple(q for normal,offset in (a,b,new,face)
                        for q in (offset,*(q for c in normal for pair in c for q in pair)))
                    with V._work(inputs,arena.resource,pairs=16*(ORDER+1)**2):
                        arena.work(128*(ORDER+1)**3)
                        bn,na=T._cross(b[0],face[0],E),T._cross(face[0],a[0],E)
                        determinant=_dot(a[0],bn,E)
                        if all(q==E.zero for q in determinant):
                            continue
                        point=tuple(E.add(E.scale(x,a[1]),E.scale(y,b[1])) for x,y in zip(bn,na))
                        numerator=E.scale(E.sub(_dot(new[0],point,E),E.scale(determinant,new[1])),sign)
                        if all(lo==hi for lo,hi in (*numerator,*determinant)):
                            result=((one,two),tuple(lo for lo,_ in numerator),tuple(lo for lo,_ in determinant))
                            arena.keep((*result[1],*result[2]),2*(ORDER+1))
                    break
            numerator_cache[key]=result
            return result
        def coincident_start(name):
            if name not in reduced_cache:
                constraint=path_record['constraints'].get(name)
                reduced_cache[name]=None if constraint is None or isinstance(name,tuple) and name[0]=='cone' \
                    else _coincident_start(constraint,start_plane(('interface',)),arena)
            return reduced_cache[name]
        def start_plane(name):
            if name in start_planes:
                return start_planes[name]
            result = None
            if isinstance(name,tuple) and name[0]=='flow':
                result=_initial_flow_plane(first,second,omega,arena)
            elif name in path_record['constraints'] and not (isinstance(name,tuple) and name[0]=='cone'):
                normal,offset=D._constraint_boxes(path_record['constraints'][name],Q(0),Q(0),T.POSE_LEVEL,arena)
                if all(lo==hi for lo,hi in normal):
                    result=tuple(lo for lo,_ in normal),offset
            elif name==('interface',) or isinstance(name,tuple) and name[0]=='cone':
                posed=[]
                for ray in (first,second):
                    vector,_,interval=D._ray_box(D._load_vec(ray['direction']),D._load_vec(ray['angular_velocity_rad_s']),
                        Q(0),Q(0),T.POSE_LEVEL,arena,D._history(ray.get('prior_rotations',())))
                    if any(lo!=hi for lo,hi in interval):
                        break
                    posed.append(vector)
                if len(posed)==2:
                    normal=O._cross(*posed)
                    result=(normal if name==('interface',) else O._cross(normal,posed[name[1]])),Q(0)
            if result is not None:
                arena.keep((*result[0],result[1]),2)
            start_planes[name]=result
            return result
        def exact_start_zero(name,active):
            key=name,active
            if key in start_cache:
                return start_cache[key]
            new,face=start_plane(name),start_plane(('interface',))
            result=False
            if new is not None and face is not None:
                result=_same_initial_plane(new,face,arena)
                for edge in active:
                    if result:
                        break
                    other=start_plane(edge)
                    if other is not None:
                        result=_initial_edge_contains(new,face,other,arena)
                if new[1]==0:
                    for i,ray in enumerate((first,second)):
                        if result:
                            break
                        if ('cone',i) not in active:
                            continue
                        vector,_,interval=D._ray_box(D._load_vec(ray['direction']),
                            D._load_vec(ray['angular_velocity_rad_s']),Q(0),Q(0),T.POSE_LEVEL,arena,
                            D._history(ray.get('prior_rotations',())))
                        with V._work((*new[0],*vector),arena.resource):
                            if all(lo==hi for lo,hi in interval) and O._dot(new[0],vector)==0:
                                result=True
                                break
                for one,two in combinations(sorted(active,key=repr),2):
                    if result:
                        break
                    a,b=start_plane(one),start_plane(two)
                    if a is None or b is None:
                        continue
                    with V._work((*a[0],a[1],*b[0],b[1],*face[0],*new[0],new[1]),arena.resource,pairs=16):
                        arena.work(128)
                        bn,na=O._cross(b[0],face[0]),O._cross(face[0],a[0])
                        determinant=O._dot(a[0],bn)
                        if not determinant:
                            continue
                        # This actual vertex satisfies N.x=0, a.x=da,
                        # b.x=db. Test the numerator exactly, without a
                        # square root, approximate pose or near-zero test.
                        numerator=tuple(a[1]*x+b[1]*y for x,y in zip(bn,na))
                        result=O._dot(new[0],numerator)==new[1]*determinant
                        break
            arena.keep((),2)
            start_cache[key]=result
            return result

        def evaluate(bounds, reference, time_radius=None, known=None, event=None, start=False):
            # ``start``: this evaluation belongs to a leaf beginning at t=0,
            # at its midpoint or on the leaf. Only there is a plane lying in
            # the face plane at t=0 represented by its reduced line; later
            # leaves keep the ordinary line and its unchanged arithmetic.
            face_jets,rate_cache={},{}
            e1, e2, cone, velocity, scales = _chart(first, second, omega, outward_sign, bounds, J, arena)
            if velocity==(J.z,J.z):
                return J.z,J.z
            lines = {('cone', 0): (J.z, J.constant(1), J.z), ('cone', 1): cone}
            for axis in range(2):
                for end in range(2):
                    lines[('rectangle', axis, end)] = tuple(J.constant(q) for q in
                        ((1, 0, -rectangle[axis][end]) if axis == 0 else (0, 1, -rectangle[axis][end])))
            def pull(normal, offset):
                return _dot(normal, e1, J), _dot(normal, e2, J), J.constant(-offset)
            def reduced(name):
                return coincident_start(name) if start else None
            def reduced_line(name, normal, sign):
                # None unless this plane is the face plane exactly at t=0.
                found=reduced(name)
                if found is None:
                    return None
                if not face_jets:
                    # The face's own ray jets on these bounds, once per pass.
                    a,b=(_ray(ray,bounds,J,arena) for ray in (first,second))
                    face_jets.update(a=a,b=b,normal=T._cross(a,b,J))
                vector=_reduced_normal(found,normal,face_jets,ray_rates,bounds,rate_cache,J,arena)
                return (*(J.scale(_dot(vector,axis,J),sign) for axis in (e1,e2)),J.z)
            for i, (normal, offset) in enumerate(fixed):
                jets=tuple(J.constant(q) for q in normal)
                lines[('voxel', i)] = reduced_line(('voxel', i), jets, 1) or pull(jets, offset)
            world_normals={}
            for name, sign, constraint in cuts:
                normal, offset = T._normal(constraint, bounds, J, arena)
                world_normals[name]=normal
                lines[name] = reduced_line(name, normal, sign) or tuple(J.scale(q, sign) for q in pull(normal, offset))
            for sign in (-1, 1):
                lines[('flow', sign)] = (*tuple(J.scale(q, sign) for q in velocity), J.z)
            # A sign certified on a containing time leaf for the identical
            # clipping prefix stays valid on every part of that leaf.
            signs = dict(known or ())
            predicate_factors={}
            world_intersections={}
            face_normal=world_rays=None
            clipping=[None]
            def rearrange(name,active,value):
                nonlocal face_normal,world_rays
                if name not in world_normals or reduced(name) is not None:
                    return value
                # The correlated form only refines an AMBIGUOUS enclosure. A
                # strict sign on the whole leaf needs no second evaluation.
                if value[0][0]>0 or value[0][1]<0:
                    return value
                for edge in active:
                    if edge not in world_normals:
                        continue
                    for section in active:
                        if not isinstance(section,tuple) or section[0] not in ('voxel','rectangle'):
                            continue
                        key=name,edge,section
                        if key not in factor_cache:
                            factor_cache[key]=_common_plane_factor(constraints[name],constraints[edge],
                                first,second,fixed[section[1]] if section[0]=='voxel' else None,arena)
                            arena.keep((),4)
                        factor=factor_cache[key]
                        if factor is None:
                            continue
                        if key not in predicate_factors:
                            try:
                                if face_normal is None:
                                    world_rays=tuple(_ray(ray,bounds,J,arena) for ray in (first,second))
                                    face_normal=T._cross(*world_rays,J)
                                direction=T._cross(world_normals[edge],face_normal,J)
                                scale=None
                                if section[0]=='voxel':
                                    q=tuple(J.constant(x) for x in fixed[section[1]][0])
                                else:
                                    axis,end=section[1:]
                                    q=world_rays[0] if axis==0 else T._cross(face_normal,world_rays[0],J)
                                    scale=J.scale(scales[0] if axis==0 else J.mul(*scales),rectangle[axis][end])
                                denominator=_dot(q,direction,J)
                                sign=next(s for n,s,_ in cuts if n==name)
                                predicate_factors[key]=_factored_predicate(factor,denominator,bounds,sign,J,arena,
                                    section_scale=scale)
                                arena.keep(tuple(Q(q) for pair in predicate_factors[key] for q in pair),ORDER+2)
                            except _Branch:
                                predicate_factors[key]=None
                        if predicate_factors[key] is not None:
                            value=_intersect_predicate(value,predicate_factors[key])
                return value
            def removable_world_crossing(name,active):
                if not isinstance(name,tuple) or name[0]!='voxel':
                    return None
                for edge in sorted(active,key=repr):
                    if not isinstance(edge,tuple) or edge[0]!='voxel' or edge==name:
                        continue
                    key=tuple(sorted((name[1],edge[1])))
                    if key not in fixed_lines:
                        fixed_lines[key]=_fixed_world_line(*(fixed[i] for i in key),arena)
                    line=fixed_lines[key]
                    if line is None:
                        continue
                    if key not in world_intersections:
                        interface=dict(kind='moving-ray-edge',rays=(first,second))
                        world=RI.intersect_world_line(interface,*line,bounds,J,arena)
                        if world is None:
                            # Tiny nonzero initial constants: exact division
                            # by t on a leaf away from 0, never a snapped zero.
                            world=RI.intersect_world_line_reduced(interface,*line,bounds,J,arena)
                        projected=None if world is None else tuple(_dot(world,axis,J) for axis in (e1,e2))
                        if projected is not None:
                            arena.keep(tuple(Q(q) for coordinate in projected for pair in coordinate for q in pair),
                                2*(ORDER+1))
                        world_intersections[key]=projected
                    if world_intersections[key] is not None:
                        return world_intersections[key]
                return None
            def contains(name, active):
                key=physical_plane_keys.get(name)
                if key is not None and any(physical_plane_keys.get(edge)==key for edge in active):
                    return True
                # Both physical planes contain the same actual boundary ray
                # of this moving face. One closed-nonzero restricted active
                # line then identifies its entire ray line, not a near hit.
                paths = ray_paths.get(name, frozenset()) & interface_paths
                for edge in active:
                    if paths & ray_paths.get(edge, frozenset()) and any(
                            q[0][0] > 0 or q[0][1] < 0 for q in lines[edge][:2]):
                        return True
                # Independent homogeneous lines intersect at the physical
                # origin. Retain this exact incidence through every cut.
                if lines[name][2] == J.z:
                    homogeneous = [edge for edge in active if lines[edge][2] == J.z]
                    for one, two in combinations(homogeneous, 2):
                        a,b = lines[one],lines[two]
                        determinant = J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0]))[0]
                        if determinant[0] > 0 or determinant[1] < 0:
                            return True
                return False
            wide={}
            def wide_jet(name):
                # Jets on [0,b]: Taylor about t=0 needs the remainder there,
                # not merely on this leaf. These operands have no pole.
                if name not in wide:
                    span=(Q(0),bounds[1])
                    if name==('interface',):
                        found=T._normal(dict(kind='moving-ray-edge',rays=(first,second)),span,J,arena)
                    elif isinstance(name,tuple) and name[0]=='cone':
                        found=T._cross(wide_jet(('interface',))[0],
                            _ray((first,second)[name[1]],span,J,arena),J),Q(0)
                    else:
                        found=T._normal(path_record['constraints'][name],span,J,arena)
                    wide[name]=found
                return wide[name]
            def numerator_event(identity, active):
                """Sign of this predicate on the leaf, or its root bracket.

                sign(f)=sign(g)*sign(det); det must exclude zero on the leaf.
                Returns ('sign',s), ('event',down,up,before,after) or None.
                """
                exact=numerator_exact(identity,active)
                if exact is None:
                    return None
                (one,two),g,det=exact
                with arena.resource.reserve(65536+8192*(ORDER+1),category='moving-interface-numerator-jets'), \
                        V._work((*g,*det),arena.resource,pairs=8*(ORDER+1)):
                    arena.work(256*(ORDER+1)**2)
                    new,face,a,b=(wide_jet(n) for n in (identity,('interface',),one,two))
                    bn,na=T._cross(b[0],face[0],J),T._cross(face[0],a[0],J)
                    determinant=_dot(a[0],bn,J)
                    point=tuple(J.add(J.scale(x,a[1]),J.scale(y,b[1])) for x,y in zip(bn,na))
                    sign=next((s for n,s,_ in cuts if n==identity),1)
                    numerator=J.scale(J.sub(_dot(new[0],point,J),J.scale(determinant,new[1])),sign)
                    span=(J.I.point(bounds[0])[0],J.I.point(bounds[1])[1])
                    bound=determinant[ORDER]
                    for k in range(ORDER-1,-1,-1):
                        bound=J.I.add(J.I.point(det[k]),J.I.mul(bound,span))
                    if bound[0]<=0<=bound[1]:
                        return None
                    def actual(value):
                        return None if value is None else value if bound[0]>0 else not value
                    # 1. The exact model's own range on this leaf.
                    model=tuple(J.I.point(q) for q in g)
                    reach=_taylor_range(model,numerator,bounds[0],bounds[1],J)
                    if reach[0]>0 or reach[1]<0:
                        return 'sign',actual(reach[0]>0)
                    # 2. A tight early-root bracket from the first nonzero term.
                    found=_start_event(g,numerator,bounds[1],J)
                    if found is not None and found[0]=='sign':
                        return 'sign',actual(found[1])
                    if found is not None:
                        _,root_first,root_last,before,after=found
                        if root_last<bounds[0]:
                            return None if after is None else ('sign',actual(after))
                        low,high=max(root_first,bounds[0]),min(root_last,bounds[1])
                        if low<=high and 2*(high-low)<bounds[1]-bounds[0]:
                            down,up=_event_grid(low,high,bounds[0],bounds[1])
                            return ('event',bounds[0] if down is None else down,up,
                                None if down is None else actual(before),
                                actual(after) if up<bounds[1] and root_last<bounds[1] else None)
                    # 3. One certified monotone root anywhere on this leaf.
                    slope=_taylor_slope(model,numerator,bounds[0],bounds[1],J)
                    found=_monotone_event(model,numerator,slope,bounds[0],bounds[1],J)
                    if found is None:
                        return None
                    return ('event',found[0],found[1],
                        actual(found[2]) if found[0]>bounds[0] else None,
                        actual(not found[2]) if found[1]<bounds[1] else None)
            def axial_sign(identity, index, active):
                # On a stationary interface ray x=lambda*d, lambda>=0, a
                # rigid homogeneous cut rotating only about d has value
                # orientation*lambda*(n0.d) for all time. A positive sign
                # holds even at lambda=0; a negative one needs lambda>0,
                # proved by the vertex's own chart coordinate along that ray.
                for i in range(2):
                    product=axial_planes.get((identity,i))
                    if not product or ('cone',i) not in active or ('cone',1-i) in active:
                        continue
                    orientation=next((s for n,s,_ in cuts if n==identity),1)
                    if product*orientation>0:
                        return True
                    if clipping[0][index][i][0][0]>0:
                        return False
                return None
            def cone_corner(index, active):
                corner=_authored_corner(clipping[0][index],active,rectangle,J)
                if corner is None:
                    return False
                if corner not in corner_cache:
                    corner_cache[corner]=_cone_corner_inside(first,second,*corner,arena)
                    arena.keep(corner,1)
                return corner_cache[corner]
            def ray_line_sign(identity, index, active):
                # The plane holds an interface boundary ray for ALL time (an
                # exact path identity), so its line is that ray's cone line.
                # Every vertex was already kept by both cone lines, so its
                # cone value is weakly positive anyway; the vertex's own
                # value is still required here (strict, or the corner's
                # Gram bound) rather than assumed from the clipping order.
                if isinstance(identity,tuple) and identity[0]=='cone':
                    return None
                held=ray_paths.get(identity,frozenset())
                for i in range(2):
                    if not held & ray_paths[('cone',i)]:
                        continue
                    arena.work(32*(ORDER+1))
                    found=_ray_line_sign(lines[identity],lines[('cone',i)],clipping[0][index],i,
                        i==1 and cone_corner(index,active),J)
                    if found is not None:
                        return found
                return None
            def face_ray_sign(identity, index, active):
                # The face's own ray lines: the second cone line at an
                # authored corner is weakly inside for ALL time (Gram bound:
                # it may touch that line, never cross it); a plane holding a
                # boundary ray has that ray's cone line.
                return True if identity==('cone',1) and cone_corner(index,active) else \
                    ray_line_sign(identity,index,active)
            def guard(identity, index, count, value, active):
                value=rearrange(identity,active,value)
                key = identity, index, count
                if time_radius is None:
                    reference[key] = value
                    if value[0][0]<0<=value[0][1] and key not in signs:
                        # One instant whose rounded value straddles zero: a
                        # vertex that stays ON a ray line (a rigid face at
                        # the saturating angle). Only the whole-time ray-line
                        # signs can speak for an instant.
                        held=face_ray_sign(identity,index,active)
                        if held is not None:
                            signs[key]=held
                    return value
                if key not in reference:
                    raise _Branch()
                displacement = (J.I.point(-time_radius)[0], J.I.point(time_radius)[1])
                mean = J.I.add(reference[key][0], J.I.mul(displacement, value[1]))
                pair = max(mean[0], value[0][0]), min(mean[1], value[0][1])
                # A reduced line's predicate is f/t. With f/factor=sum(c[k]*t**k)
                # exact and c[0]=0, its own prefix is c[1:] and its exact start
                # is c[1]: the start and Taylor rules below never read the
                # unreduced prefix. (numerator_event still reads f=g/det, but
                # only its SIGN and roots, which f/t shares for t>0.)
                plain = reduced(identity) is None
                def exact_prefix():
                    exact=exact_coefficients(identity,active)
                    return exact if plain else _reduced_prefix(exact)
                if plain:
                    zero_start = bounds[0]==0 and exact_start_zero(identity,active)
                else:
                    zero_start = bounds[0]==0 and pair[0]<0<=pair[1] and key not in signs and \
                        _reduced_zero_start(exact_coefficients(identity,active))
                if zero_start:
                    departure=J.I.mul((J.I.point(0)[0],J.I.point(bounds[1])[1]),value[1])
                    pair=max(pair[0],departure[0]),min(pair[1],departure[1])
                    if value[1][0]>0:
                        signs[key]=True
                    elif value[1][1]<0:
                        signs[key]=False
                    if key not in signs:
                        exact=exact_prefix()
                        if exact is not None:
                            coefficients,axis=exact
                            factor=J.constant(1) if axis is None else scales[0] if axis==0 else J.mul(*scales)
                            departure,open_sign=_scaled_departure(coefficients,value,factor,bounds[1],J)
                            if departure is not None:
                                pair=max(pair[0],departure[0]),min(pair[1],departure[1])
                            if open_sign is not None:
                                signs[key]=open_sign
                elif bounds[0]==0 and pair[0]<0<=pair[1]:
                    # Only an actually ambiguous closed-leaf sign consults the
                    # exact initial jets; a proved zero start is handled above.
                    exact=exact_prefix()
                    if exact is not None and exact[0][0]!=0:
                        coefficients,axis=exact
                        factor=J.constant(1) if axis is None else scales[0] if axis==0 else J.mul(*scales)
                        with V._work(coefficients,arena.resource):
                            enclosure,closed_sign=_initial_value_enclosure(coefficients,value,factor,bounds[1],J)
                        pair=max(pair[0],enclosure[0]),min(pair[1],enclosure[1])
                        if closed_sign is not None:
                            signs[key]=closed_sign
                if pair[0]<0<=pair[1] and key not in signs:
                    axial=axial_sign(identity,index,active)
                    if axial is not None:
                        signs[key]=axial
                        pair=(max(pair[0],0),pair[1]) if axial else (pair[0],min(pair[1],0))
                located=None
                if pair[0]<0<=pair[1] and key not in signs:
                    found=numerator_event(identity,active)
                    if found is not None and found[0]=='sign' and found[1] is not None:
                        signs[key]=found[1]
                    elif found is not None and found[0]=='event':
                        located=(found[1],found[2],key,found[3],found[4])
                if pair[0]<0<=pair[1] and key not in signs and located is None:
                    # Order-ORDER midpoint model of the SAME predicate: its
                    # leaf-wide slope, and certified values at both leaf ends.
                    model=reference[key]
                    slope=_taylor_slope(model,value,-time_radius,time_radius,J)
                    slope=max(slope[0],value[1][0]),min(slope[1],value[1][1])
                    if slope[0]>slope[1]:
                        raise V.VolumeError('moving-interface predicate slope enclosures contradict')
                    value=(value[0],slope,*value[2:])
                    monotone=slope[0]>0 or slope[1]<0
                    if monotone:
                        ends=tuple(_taylor_point(model,value,offset,J) for offset in (-time_radius,time_radius))
                        pair=(max(pair[0],min(ends[0][0],ends[1][0])),
                              min(pair[1],max(ends[0][1],ends[1][1])))
                        if zero_start:
                            signs[key]=slope[0]>0
                    if pair[0]<0<=pair[1] and key not in signs and bounds[0]==0:
                        exact=exact_prefix()
                        factor=None if exact is None else (J.constant(1) if exact[1] is None else
                            scales[0] if exact[1]==0 else J.mul(*scales))
                        if factor is not None and factor[0][0]>0:
                            with V._work(exact[0],arena.resource,pairs=4*(ORDER+1)):
                                arena.work(64*(ORDER+1))
                                found=_start_event(exact[0],J.div(value,factor),bounds[1],J)
                                if found is not None and found[0]=='sign':
                                    signs[key]=found[1]
                                elif found is not None:
                                    down,up=_event_grid(found[1],found[2],Q(0),bounds[1])
                                    located=(Q(0) if down is None else down,up,key,
                                        None if down is None else found[3],
                                        found[4] if up<bounds[1] else None)
                    if located is None and pair[0]<0<=pair[1] and key not in signs and monotone:
                        arena.work(64*(ORDER+1))
                        found=_monotone_event(model,value,slope,-time_radius,time_radius,J)
                        if found is not None:
                            middle=(bounds[0]+bounds[1])/2
                            located=(middle+found[0],middle+found[1],key,
                                found[2] if found[0]>-time_radius else None,
                                (not found[2]) if found[1]<time_radius else None)
                if pair[0]<0<=pair[1] and key not in signs:
                    # Still open: the face's own ray lines, last of all. A
                    # whole-leaf sign supersedes any bracket found above.
                    held=face_ray_sign(identity,index,active)
                    if held is not None:
                        signs[key]=held
                        located=None
                        pair=(max(pair[0],0),pair[1]) if held else (pair[0],min(pair[1],0))
                if located is not None and key not in signs and event is not None and event[0] is None:
                    arena.keep(located[:2],2)
                    event[0]=located
                if pair[0] > pair[1]:
                    raise V.VolumeError('moving-interface predicate enclosures contradict')
                strict = T._strict_interior_sign((pair, *value[1:]), bounds)
                if strict is not None:
                    signs[key] = strict
                return (pair, *value[1:])
            def clip(polygon, name):
                clipping[0]=polygon
                return T._clip(polygon, lines[name], name, J, incidence=contains, guard=guard,
                    classification=lambda identity, index, count: signs.get((identity, index, count)),
                    intersection=lambda line, active: T._active_intersection(line, active, lines.__getitem__, J,
                        removable=lambda:removable_world_crossing(name,active)))
            polygon = tuple((J.constant(u), J.constant(v), frozenset(
                ('rectangle', axis, end) for axis, q in enumerate((u, v)) for end in range(2)
                if q == rectangle[axis][end])) for u, v in W._rectangle(rectangle))
            for name in (('cone', 0), ('cone', 1), *(('voxel', i) for i in range(len(fixed))),
                         *(name for name, _, _ in cuts)):
                polygon = clip(polygon, name)
                if not polygon:
                    return J.z, J.z
            result = []
            for sign in (-1, 1):
                clipped = clip(polygon, ('flow', sign))
                outer = C.first_moments(clipped, radius**2, J, arena, fixed_axis_coordinates=rectangle)
                inner = C.first_moments(clipped, layer.bottom_radius_m**2, J, arena,
                                        fixed_axis_coordinates=rectangle)
                result.append(J.scale(J.add(*(J.mul(velocity[i], J.sub(outer[i], inner[i]))
                    for i in range(2))), sign))
            return tuple(result)

        def leaf(a, b, level, known=None, attempt=True):
            """Return (bounds, event). An event is a certified root bracket
            (t1,t2,key,sign on [a,t1],sign on [t2,b]) of the first predicate
            whose sign changes inside this leaf; None where nothing is proved.
            The bracket itself always keeps the original geometric kernel."""
            original = fallback(a, b, level)
            if not attempt or all(lo == hi for lo, hi in original):
                return original, None
            arena.work(64*(ORDER+1)**2*(planes+4))
            event = [None]
            try:
                middle, time_radius = (a+b)/2, (b-a)/2
                reference = {}
                coefficients = evaluate((middle, middle), reference, known=known, start=a==0)
                with arena.resource.reserve(4096+256*(ORDER+1)*len(reference),
                                            category='moving-interface-midpoint-jets'):
                    derivatives = evaluate((a, b), reference, time_radius, known=known, event=event, start=a==0)
                result = []
                for old, coefficient, derivative in zip(original, coefficients, derivatives):
                    value = J.zero
                    for k in range(0, ORDER, 2):
                        value = J.I.add(value, J.I.mul(coefficient[k], J.I.point(2*time_radius**(k+1)/Q(k+1))))
                    value = J.I.add(value, J.I.mul(derivative[ORDER],
                        J.I.point(2*time_radius**(ORDER+1)/Q(ORDER+1))))
                    pair = max(old[0], Q(value[0])), min(old[1], Q(value[1]))
                    if pair[0] > pair[1]:
                        raise V.VolumeError('moving-interface Taylor integral contradicts physical geometry')
                    result.append(pair)
                return tuple(result), None
            except _Branch:
                return original, event[0]

        initial, located = leaf(Q(0), duration, 0)
        arena.keep(tuple(q for pair in initial for q in pair), 8)
        totals = [list(pair) for pair in initial]
        queue, serial, leaves = [], 0, 1
        def push(a, b, level, values, known, located):
            nonlocal serial
            error = max(hi-lo for lo, hi in values)
            if error:
                serial += 1
                heapq.heappush(queue, (-error, serial, a, b, level, values, known, located))
        push(Q(0), duration, 0, initial, None, located)
        while queue and any(hi-lo > width for (lo, hi), width in zip(totals, widths)) and leaves < max_leaves:
            _, _, a, b, level, old, known, located = heapq.heappop(queue)
            parts = None
            if located is not None:
                # Split AT the certified event, not blindly at the midpoint:
                # each side inherits its proved sign and the short bracket
                # stays with the original kernel. Every part is a real leaf.
                t1, t2, key, before, after = located
                parts = [(lo, hi, sign, resolved) for lo, hi, sign, resolved in
                         ((a, t1, before, True), (t1, t2, None, False), (t2, b, after, True)) if lo < hi]
                if (not a <= t1 <= t2 <= b or 2*(t2-t1) > b-a or len(parts) < 2 or
                        leaves+len(parts)-1 > max_leaves):
                    parts = None
            if parts is None:
                middle = (a+b)/2
                key = None
                parts = [(a, middle, None, True), (middle, b, None, True)]
            children = []
            for ca, cb, sign, resolved in parts:
                inherited = known if sign is None else {**(known or {}), key: sign}
                values, found = leaf(ca, cb, level+1, inherited, resolved)
                arena.keep((ca,cb,*(q for pair in values for q in pair)),8)
                children.append(values)
                push(ca, cb, level+1, values, inherited, found)
            with V._work(tuple(q for pair in old for q in pair)+tuple(
                    q for values in children for pair in values for q in pair), arena.resource, pairs=16):
                for i in range(2):
                    for j in range(2):
                        totals[i][j] += sum(values[i][j] for values in children)-old[i][j]
            arena.keep(tuple(q for pair in totals for q in pair), 8)
            leaves += len(parts)-1
        source_digest()
        return tuple(tuple(pair) for pair in totals), leaves, all(
            hi-lo <= width for (lo, hi), width in zip(totals, widths))
