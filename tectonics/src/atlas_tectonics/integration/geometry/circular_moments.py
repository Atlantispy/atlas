"""Certified disk/polygon first moments using oriented lines and circular arcs.

The supplied polygon and all its temporal jets share one orthonormal chart
whose origin is the disk centre. No sampling, angle approximation or full-disk
substitution is used. Unproved line/circle topology raises the existing Branch
exception for the caller's original bounded enclosure/refinement.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from contextlib import contextmanager

from atlas_tectonics.integration.coupling.q2_directed import _Branch
from . import volume as V

METHOD='disk-polygon-first-moment:oriented-line-arc-jets-v1'


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


def _roots(a,b,r2,J,edge,dot_a,dot_b):
    """Return ordered infinite-line intersections, or None if no crossings.

    ``edge`` is this edge's radius-free [d, A, B] table, filled on first use;
    ``dot_a``/``dot_b`` return the endpoints' cached squared lengths.
    """
    if not edge:
        d=tuple(J.sub(y,x) for x,y in zip(a,b))
        edge+=(d,_dot(d,d,J))
    d,A=edge[:2]
    if A==J.z:
        return None
    if A[0][0]<=0:
        raise _Branch()
    if len(edge)==2:
        edge.append(J.scale(_dot(a,d,J),2))
    B=edge[2]
    C=J.sub(dot_a(),J.constant(r2))
    D=J.sub(J.mul(B,B),J.scale(J.mul(A,C),4))
    if D==J.z or D[0][1]<0:
        return None  # Tangency changes no two-dimensional first moment.
    if D[0][0]<=0:
        raise _Branch()
    # Exact endpoint roots must not be re-created by cancelling rounded roots.
    if C==J.z:
        return _ordered(J.z,J.div(J.neg(B),A),J)
    if J.sub(dot_b(),J.constant(r2))==J.z:
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
    elif start[0]>=0 and end[1]<0:
        interior=0
    else:
        return None
    root=roots[interior]
    pair=max(root[0][0],J.I.point(0)[0]),min(root[0][1],J.I.point(1)[1])
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
    with V._work((r2,*(q for pair in bounds for q in pair)),arena.resource,pairs=8, convert_values=False):
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
                arena.work(2*len(J.z))
                tightened=tuple((max(a[0],b[0]),min(a[1],b[1]))
                    for a,b in zip(jets[axis],authority[axis][end]))
                jets[axis]=tightened
            result.append((*jets,*point[2:]))
        yield tuple(result)


def annular_first_moments(polygon,outer_r2,inner_r2,J,arena,*,fixed_axis_coordinates=None):
    """Return (outer, inner): jets of integral (x,y) dA on each disk intersection.

    ``polygon`` contains pairs of coordinate jets of a CCW polygon. Optional
    issued rectangle tags may use exact ``fixed_axis_coordinates`` in this
    centred chart; all other incidence tags are ignored. The caller proves
    simplicity/orientation and performs time integration, including its
    original error/leaf ceilings. The first moment of a full circle is zero,
    so each exterior edge portion may use its oriented radial-projection arc
    without an atan or winding branch. Annular moments are outer-inner, not
    disk area.

    One pass serves both radii. The polygon is tightened once; radius-free
    vertex lengths, their roots and edge (d, A, B) products are kept in
    tables filled on first use. Each radius runs the single-disk edge loop
    with its own charges, and the skipped second tightening's work units are
    charged where that tightening ran.
    """
    radii=(Q(outer_r2),Q(inner_r2))
    if len(polygon)<3 or all(r2<=0 for r2 in radii):
        return (J.z,J.z),(J.z,J.z)
    order=len(J.z)-1
    results=[];ran=False;before=arena.work_units
    with _rectangle_coordinate_jets(polygon,fixed_axis_coordinates,J,arena) as polygon, \
            arena.resource.reserve(65536+384*(order+1)**2,category='circular-first-moment-jets'):
        tightening=arena.work_units-before
        points=tuple(raw[:2] for raw in polygon)
        dots=[None]*len(points);norms=[None]*len(points);edges=[[] for _ in points]

        def dot(i):
            if dots[i] is None:
                dots[i]=_dot(points[i],points[i],J)
            return dots[i]

        def norm(i):
            if norms[i] is None:
                norms[i]=_sqrt(dot(i),J)
            return norms[i]

        for r2 in radii:
            if r2<=0:
                results.append((J.z,J.z))
                continue
            if ran and tightening:
                arena.work(tightening)  # the second tightening this pass skips
            ran=True
            results.append(_disk_first_moments(points,r2,J,arena,order,dot,norm,edges))
    return tuple(results)


def _disk_first_moments(points,r2,J,arena,order,dot,norm,edges):
    """One disk's edge loop over the shared vertex/edge tables."""
    radius=_sqrt(J.constant(r2),J)
    total=[J.z,J.z]
    n=len(points)

    def add(values):
        for i,value in enumerate(values):
            total[i]=J.add(total[i],value)

    def project(point,on_circle,index):
        if on_circle:
            return point
        length=_sqrt(_dot(point,point,J),J) if index is None else norm(index)
        scale=J.div(radius,length)
        return tuple(J.mul(q,scale) for q in point)

    def arc(a,b,ia,ib,a_circle=False,b_circle=False):
        a,b=project(a,a_circle,ia),project(b,b_circle,ib)
        add((J.scale(J.sub(b[1],a[1]),r2/3),J.scale(J.sub(a[0],b[0]),r2/3)))

    def line(a,b):
        cross=J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0]))
        add(tuple(J.scale(J.mul(cross,J.add(x,y)),Q(1,6)) for x,y in zip(a,b)))

    for i in range(n):
        j=(i+1)%n
        arena.work(128*(order+1)**2)
        a,b=points[i],points[j]
        if a==b:
            continue
        # A disk is convex: complete endpoint enclosures inside the
        # closed disk certify the complete segment, even if its length
        # vanishes or two exact-equal endpoints have distinct interval
        # representations. Retain both representations and their line
        # integral; do not infer equality or attempt unnecessary roots.
        if (dot(i)[0][1] <= r2 and dot(j)[0][1] <= r2):
            line(a,b)
            continue
        # A short/collapsing exterior edge needs no line-circle roots.
        # Prove complete chord separation, not merely outside endpoints;
        # keep its directed arc and all distinct endpoint jets unchanged.
        if _segment_box_outside(a,b,r2,arena):
            arc(a,b,i,j)
            continue
        roots=_roots(a,b,r2,J,edges[i],lambda:dot(i),lambda:dot(j))
        if roots is None:
            arc(a,b,i,j)
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
            arc(a,b,i,j)
            continue
        delta=edges[i][0]  # _roots filled it: the same b-a jets

        def point(t):
            if t==J.z:
                return a,i
            if t==J.constant(1):
                return b,j
            return tuple(J.add(x,J.mul(t,d)) for x,d in zip(a,delta)),None
        (start,i_start),(end,i_end)=point(lo),point(hi)
        if lo!=J.z:
            arc(a,start,i,i_start,b_circle=lo_circle)
        line(start,end)
        if hi!=J.constant(1):
            arc(end,b,i_end,j,a_circle=hi_circle)
    return tuple(total)
