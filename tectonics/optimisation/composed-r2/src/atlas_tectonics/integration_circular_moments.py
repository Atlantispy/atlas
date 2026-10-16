"""Certified disk/polygon first moments using oriented lines and circular arcs.

The supplied polygon and all its temporal jets share one orthonormal chart
whose origin is the disk centre. No sampling, angle approximation or full-disk
substitution is used. Unproved line/circle topology raises the existing Branch
exception for the caller's original bounded enclosure/refinement.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from contextlib import contextmanager
import hashlib
from pathlib import Path

from .integration_q2_directed import _Branch, source_digest as interval_digest
from . import integration_volume as V

_LOADED=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
METHOD='disk-polygon-first-moment:oriented-line-arc-jets-v1'


def source_digest():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=_LOADED:
        raise V.VolumeError('circular first-moment source changed after loading')
    return hashlib.sha256((_LOADED+interval_digest()).encode('ascii')).hexdigest()


def _sqrt(value,J):
    if value==J.z:
        return J.z
    coefficients=[J.I.sqrt(value[0])]
    denominator=J.I.mul(J.I.point(2),coefficients[0])
    for k in range(1,len(value)):
        tail=J.zero
        for i in range(1,k):
            tail=J.I.add(tail,J.I.mul(coefficients[i],coefficients[k-i]))
        coefficients.append(J.I.div(J.I.sub(value[k],tail),denominator))
    return tuple(coefficients)


def _dot(a,b,J):
    return J.add(J.mul(a[0],b[0]),J.mul(a[1],b[1]))


def _ordered(a,b,J):
    difference=J.sub(b,a)
    if difference==J.z or difference[0][0]>0:
        return a,b
    if difference[0][1]<0:
        return b,a
    raise _Branch()


def _roots(a,b,r2,J):
    """Return ordered infinite-line intersections, or None if no crossings."""
    d=tuple(J.sub(y,x) for x,y in zip(a,b))
    A=_dot(d,d,J)
    if A==J.z:
        return None
    if A[0][0]<=0:
        raise _Branch()
    B=J.scale(_dot(a,d,J),2)
    C=J.sub(_dot(a,a,J),J.constant(r2))
    D=J.sub(J.mul(B,B),J.scale(J.mul(A,C),4))
    if D==J.z or D[0][1]<0:
        return None  # Tangency changes no two-dimensional first moment.
    if D[0][0]<=0:
        raise _Branch()
    # Exact endpoint roots must not be re-created by cancelling rounded roots.
    if C==J.z:
        return _ordered(J.z,J.div(J.neg(B),A),J)
    if J.sub(_dot(b,b,J),J.constant(r2))==J.z:
        return _ordered(J.constant(1),J.div(C,A),J)
    root=_sqrt(D,J);denominator=J.scale(A,2)
    return J.div(J.sub(J.neg(B),root),denominator),J.div(J.add(J.neg(B),root),denominator)


def _clamp_root(root,J):
    """Position relative to [0,1], proved for the complete temporal interval."""
    if root==J.z or root[0][1]<0:
        return J.z,False
    one=J.constant(1)
    if root==one or root[0][0]>1:
        return one,False
    if root[0][0]>0 and root[0][1]<1:
        return root,True
    raise _Branch()


def _squared_norm_value(point,J):
    """Exact coordinate-box square enclosure; do not multiply x independently.

    This is only a value bound. The supplied physical coordinate derivative
    jets remain unchanged in every circle/root construction.
    """
    total=J.zero
    for coordinate in point:
        lo,hi=coordinate[0]
        left=J.I.mul((lo,lo),(lo,lo));right=J.I.mul((hi,hi),(hi,hi))
        lower=J.I.point(0)[0] if lo<=0<=hi else min(left[0],right[0])
        total=J.I.add(total,(lower,max(left[1],right[1])))
    return total


def _endpoint_root_positions(a,b,r2,roots,J):
    """Ordered quadratic roots from WHOLE-interval endpoint signs.

    With positive length squared, an inside start and outside end imply
    lower<0<upper<=1; reversed signs imply0<=lower<1<upper. The non-inside
    endpoint may lie exactly on the circle. This can certify
    topology when subtractive root arithmetic straddles an endpoint. Only
    the value enclosure is intersected with[0,1]; every derivative and the
    actual on-circle root are retained. Uncertain inward endpoints decline.
    """
    delta=tuple(J.sub(y,x) for x,y in zip(a,b))
    if _squared_norm_value(delta,J)[0]<=0:
        return None
    start=J.I.sub(_squared_norm_value(a,J),J.I.point(r2))
    end=J.I.sub(_squared_norm_value(b,J),J.I.point(r2))
    if start[1]<0 and end[0]>=0:
        interior=1
        if roots[0][0][0]>=0:
            raise V.VolumeError('circle root contradicts strict endpoint signs')
    elif start[0]>=0 and end[1]<0:
        interior=0
        if roots[1][0][1]<=1:
            raise V.VolumeError('circle root contradicts strict endpoint signs')
    else:
        return None
    root=roots[interior]
    pair=max(root[0][0],J.I.point(0)[0]),min(root[0][1],J.I.point(1)[1])
    if (pair[0]>pair[1] or (pair[1]<=0 if interior else pair[0]>=1) or
            (interior==1 and end[0]>0 and pair[0]>=1) or
            (interior==0 and start[0]>0 and pair[1]<=0)):
        raise V.VolumeError('circle root contradicts strict interior crossing')
    bounded=(pair,*root[1:])
    return (J.z,False,bounded,True) if interior==1 else (bounded,True,J.constant(1),False)


def _segment_box_outside(a,b,r2,arena):
    """Separation of the WHOLE segment from the disk's open interior.

    Endpoint-outside alone is insufficient. The complete interval endpoint
    hull contains every chord point at every time, so its exact minimum
    squared distance is a valid lower bound. For a positive-radius disk,
    equality can only add a tangent point, not an interior line portion.
    Its existing directed radial arc is therefore still the correct term.
    A lower bound below the radius remains undecided, however small the gap.
    """
    bounds=tuple((min(Q(x[0][0]),Q(y[0][0])),max(Q(x[0][1]),Q(y[0][1])))
                 for x,y in zip(a,b))
    with V._work((r2,*(q for pair in bounds for q in pair)),arena.resource,pairs=8):
        arena.work(32)
        lower=sum((lo*lo if lo>0 else hi*hi if hi<0 else Q(0) for lo,hi in bounds),Q(0))
        return r2>0 and lower>=r2


@contextmanager
def _rectangle_coordinate_jets(polygon,coordinates,J,arena):
    """Intersect issued rectangle-coordinate authority with every jet term.

    The optional coordinates are exact bounds in THIS centred disk chart.
    An active ('rectangle',axis,end) tag certifies a fixed coordinate, not a
    nearby value. Untagged/unsupported identities retain their input jets.
    """
    if coordinates is None:
        yield polygon
        return
    if (type(coordinates) not in (tuple,list) or len(coordinates)!=2 or
            any(type(pair) not in (tuple,list) or len(pair)!=2 for pair in coordinates) or
            any(type(q) not in (int,Q) for pair in coordinates for q in pair)):
        raise V.VolumeError('fixed rectangle coordinates require two exact rational bound pairs')
    bits=sum(V._bits(q) for pair in coordinates for q in pair)
    # The input polygon/identities remain borrowed. Charge the four exact
    # coordinate conversions, new constant/intersection jets and point/tuple
    # containers while the tightened polygon is live; never retain a cache.
    size=4096+128*bits+512*(4+2*len(polygon))*len(J.z)
    with arena.resource.reserve(size,category='circular-fixed-coordinate-jets'):
        authority=tuple(tuple(J.constant(q) for q in pair) for pair in coordinates)
        result=[]
        for point in polygon:
            jets=list(point[:2])
            for tag in (() if len(point)<3 else point[2]):
                if (type(tag) is not tuple or len(tag)!=3 or tag[0]!='rectangle' or
                        type(tag[1]) is not int or type(tag[2]) is not int or
                        tag[1] not in (0,1) or tag[2] not in (0,1)):
                    continue
                axis,end=tag[1:]
                if len(jets[axis])!=len(J.z):
                    raise V.VolumeError('rectangle coordinate jet has the wrong order')
                arena.work(2*len(J.z))
                tightened=tuple((max(a[0],b[0]),min(a[1],b[1]))
                    for a,b in zip(jets[axis],authority[axis][end]))
                if any(lo>hi for lo,hi in tightened):
                    raise V.VolumeError('rectangle coordinate authority contradicts the supplied jet')
                jets[axis]=tightened
            result.append((*jets,*point[2:]))
        yield tuple(result)


def first_moments(polygon,radius_squared,J,arena,*,fixed_axis_coordinates=None):
    """Return jets of integral (x,y) dA on disk intersection with a CCW polygon.

    ``polygon`` contains pairs of coordinate jets. Optional issued rectangle
    tags may use exact ``fixed_axis_coordinates`` in this centred chart; all
    other incidence tags are ignored. The caller proves simplicity/orientation and
    performs time integration, including its original error/leaf ceilings.
    The first moment of a full circle is zero, so each exterior edge portion
    may use its oriented radial-projection arc without an atan or winding
    branch. Annular moments are the difference of two calls, not disk area.
    """
    source_digest();r2=Q(radius_squared)
    if r2<=0 or len(polygon)<3:
        return J.z,J.z
    order=len(J.z)-1
    with _rectangle_coordinate_jets(polygon,fixed_axis_coordinates,J,arena) as polygon, \
            arena.resource.reserve(65536+384*(order+1)**2,category='circular-first-moment-jets'):
        radius=_sqrt(J.constant(r2),J)
        total=[J.z,J.z]

        def add(values):
            for i,value in enumerate(values):
                total[i]=J.add(total[i],value)

        def project(point,on_circle):
            if on_circle:
                return point
            scale=J.div(radius,_sqrt(_dot(point,point,J),J))
            return tuple(J.mul(q,scale) for q in point)

        def arc(a,b,a_circle=False,b_circle=False):
            a,b=project(a,a_circle),project(b,b_circle)
            add((J.scale(J.sub(b[1],a[1]),r2/3),J.scale(J.sub(a[0],b[0]),r2/3)))

        def line(a,b):
            cross=J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0]))
            add(tuple(J.scale(J.mul(cross,J.add(x,y)),Q(1,6)) for x,y in zip(a,b)))

        for raw_a,raw_b in zip(polygon,(*polygon[1:],polygon[0])):
            arena.work(128*(order+1)**2)
            a,b=raw_a[:2],raw_b[:2]
            if a==b:
                continue
            # A disk is convex: complete endpoint enclosures inside the
            # closed disk certify the complete segment, even if its length
            # vanishes or two exact-equal endpoints have distinct interval
            # representations. Retain both representations and their line
            # integral; do not infer equality or attempt unnecessary roots.
            if (_dot(a,a,J)[0][1] <= r2 and _dot(b,b,J)[0][1] <= r2):
                line(a,b)
                continue
            # A short/collapsing exterior edge needs no line-circle roots.
            # Prove complete chord separation, not merely outside endpoints;
            # keep its directed arc and all distinct endpoint jets unchanged.
            if _segment_box_outside(a,b,r2,arena):
                arc(a,b)
                continue
            roots=_roots(a,b,r2,J)
            if roots is None:
                arc(a,b)
                continue
            try:
                lo,lo_circle=_clamp_root(roots[0],J)
                hi,hi_circle=_clamp_root(roots[1],J)
            except _Branch:
                arena.work(32*(order+1)**2)
                positions=_endpoint_root_positions(a,b,r2,roots,J)
                if positions is None:
                    raise
                lo,lo_circle,hi,hi_circle=positions
            if lo==hi:
                arc(a,b)
                continue
            delta=tuple(J.sub(y,x) for x,y in zip(a,b))
            def point(t):
                if t==J.z:
                    return a
                if t==J.constant(1):
                    return b
                return tuple(J.add(x,J.mul(t,d)) for x,d in zip(a,delta))
            start,end=point(lo),point(hi)
            if lo!=J.z:
                arc(a,start,b_circle=lo_circle)
            line(start,end)
            if hi!=J.constant(1):
                arc(end,b,a_circle=hi_circle)
    source_digest()
    return tuple(total)
