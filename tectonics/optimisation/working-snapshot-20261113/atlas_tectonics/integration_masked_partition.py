"""Certified rectangular partition of a moving tensor-Q2 material mask.

Only the intersection of a sign curve and an unresolved moving boundary needs
spatial refinement. Whole rectangles reuse directed Q2 integration; signed
regions reuse actual moving-mask moments. An unresolved rectangle retains a
nonzero stream cap from its certified occupied time-area. Exact disjoint
rectangles cover the original face, and their interval SUM must satisfy the
original physical error. The work ceiling is not an error allowance.

The worst rectangle is cut, in this order: at the certified all-time-inside
boundary of the mask; at the certified one-sign boundary of the normal trace,
moved out of each stretch a moving boundary sweeps across a new corner unless
that stretch reaches the kept end of the side; else at the midpoint across
the direction of largest variation. Every cut gives a valid exact partition
and so a certified enclosure of the same streams: a cut rule changes only
how many leaves a query needs to reach its width. No rule is claimed to need
no more leaves than bisection of the longer side on every query.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path

from . import integration_masked_native as NM
from . import integration_moving_face_moments as TM
from . import integration_volume as V
from . import integration_volume_bounds as B
from .regional_heat3d import _cancel

METHOD='moving-mask-Q2:certified-spatial-partition:global-interval-sum-v1'
_LOADED=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def source_digest():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=_LOADED:
        raise V.VolumeError('masked spatial integration source changed after loading')
    return hashlib.sha256((_LOADED+NM.source_digest()).encode('ascii')).hexdigest()


class _PoseCache:
    """Query-local exact-input cache; no rounded key or cross-query storage."""
    def __init__(self,arena):
        self.arena=arena
        self.values={}
        self.hits=self.misses=0
        arena.keep((),objects=4)

    def boxes(self,constraint,a,b,level,arena):
        from . import integration_differential_geometry as G
        if arena.resource is not self.arena.resource:
            raise V.VolumeError('posed-constraint cache has another query budget')
        # The source record was admitted by the caller. Charge transient codec
        # space before serialising; the immutable complete key distinguishes
        # every declared plane, pose history, time interval and precision.
        from .integration_regional_inventory import _width
        with arena.resource.reserve(4096+8*_width(constraint),category='masked-pose-key'):
            encoded=json.dumps(constraint,sort_keys=True,separators=(',',':'),allow_nan=False)
            key=(encoded,a,b,level)
            if key in self.values:
                self.hits+=1
                return self.values[key]
            answer=G._constraint_boxes(constraint,a,b,level,arena)
            normal,offset=answer
            self.arena.keep((*[q for pair in normal for q in pair],offset,a,b),objects=8)
            self.arena.stack.enter_context(arena.resource.reserve(256+2*len(encoded),category='masked-pose-cache'))
            self.values[key]=answer
            self.misses+=1
            return answer


class _ScratchArena(B._Arena):
    """Temporary child proofs unwind; ALL attempted work stays on the parent."""
    def __init__(self,parent):
        super().__init__(parent.resource)
        self.parent=parent

    def work(self,count):
        self.parent.work(count)
        self.work_units+=count


def _aggregate(nodes,widths,arena):
    """Sequential exact sums: each real growing accumulator is admitted.

    Unrelated denominators may grow, but all input operands are NOT used in
    one simultaneous product. Preflight each addition and keep the four final
    sums; this accounts their true width without an all-node scratch product.
    """
    arena.work(16+8*len(nodes))
    values=[]
    for j in range(2):
        pair=[]
        for k in range(2):
            total=Q(0)
            for node in nodes:
                value=node['values'][j][k]
                with V._work((total,value),arena.resource):
                    total+=value
            pair.append(total)
        values.append(tuple(pair))
    values=tuple(values)
    arena.keep(tuple(q for pair in values for q in pair),objects=4)
    with V._work((*[q for pair in values for q in pair],*widths),arena.resource):
        met=all(hi-lo<=width for (lo,hi),width in zip(values,widths))
    worst,index=Q(-1),0
    for i,node in enumerate(nodes):
        with V._work((*[q for pair in node['values'] for q in pair],worst),arena.resource):
            error=max(hi-lo for lo,hi in node['values'])
            if error>worst:
                worst,index=error,i
    return values,met,index


def _split_axis(normal,bounds,arena):
    """Subdivision direction of largest certified variation of the normal trace.

    An unresolved rectangle holds a sign curve of the Q2 normal polynomial and
    a moving mask boundary. Its stream cap falls only when a cut separates
    them, which a cut ACROSS the direction of variation does. The variation
    along axis j is bounded by sup|dp/dx_j| times the side (the exact
    Bernstein hull of the derivative on this rectangle): the maximum-smear
    rule of interval subdivision. Equal variations, and a constant trace,
    keep the longer side and then the first axis, as the original rule did.
    """
    sides=tuple(hi-lo for lo,hi in bounds)
    smear=[]
    with V._work((*normal.values(),*[q for pair in bounds for q in pair]),arena.resource):
        for axis in range(2):
            derivative={}
            for key,value in normal.items():
                if key[axis]:
                    lower=(key[0]-1,key[1]) if axis==0 else (key[0],key[1]-1)
                    derivative[lower]=derivative.get(lower,Q(0))+key[axis]*value
            low,high=NM._bernstein_range(NM._unit_polynomial(derivative,bounds)) if derivative else (Q(0),Q(0))
            smear.append(max(abs(low),abs(high))*sides[axis])
    arena.work(64)
    return max(range(2),key=lambda j:(smear[j],sides[j],-j))


def _contained_cut(record,component,face,bounds,duration,arena,cache):
    """A cut at the certified all-time-inside boundary of the moving mask.

    Each constraint's whole-interval inner line is affine on this rectangle,
    so along either axis the part that keeps one side and satisfies every
    inner line at both of its far corners is one rectangle wholly inside the
    mask for the complete interval: the directed Q2 integral applies to it
    with no moving boundary at all. When that part is at least half of the
    rectangle and not all of it, cutting there removes more than a bisection
    and leaves every moving boundary in the thin remainder. The coordinate is
    rounded TOWARDS the kept side, to a dyadic step no coarser than a quarter
    of the remainder, so containment still holds and later rectangles keep
    short coordinates. Returns (axis, coordinate) or None; None defers to
    the one-sign cut and then to the midpoint across the largest variation.
    Any cut gives a valid exact partition.
    """
    from . import integration_differential_geometry as G
    child=(*face[:4],bounds)
    lines=[]
    for name,sign in component['constraints']:
        normal,offset=NM._posed_box(record['constraints'][name],duration,arena,cache)
        with V._work((*[q for pair in normal for q in pair],offset,
                      *[q for vector in face[:3] for q in vector],
                      *[q for pair in bounds for q in pair]),arena.resource):
            lines.append(G._boxed_constraint_line(child,bounds,normal,offset,sign,True))
    arena.work(64+64*len(lines))
    best=None
    with V._work((*[q for line in lines for q in line],*[q for pair in bounds for q in pair]),arena.resource):
        for axis in range(2):
            lo,hi=bounds[axis];side=hi-lo
            for keep_low in (True,False):
                start,limit=(lo,hi) if keep_low else (hi,lo)
                inside=True
                for line in lines:
                    slope=line[axis]
                    for other in bounds[1-axis]:
                        constant=line[1-axis]*other+line[2]
                        if slope*start+constant<0:
                            inside=False;break
                        if keep_low and slope<0:
                            limit=min(limit,-constant/slope)
                        elif not keep_low and slope>0:
                            limit=max(limit,-constant/slope)
                    if not inside:
                        break
                if not inside:
                    continue
                length=limit-lo if keep_low else hi-limit
                if not side/2<=length<side:
                    continue
                remainder=side-length
                steps=1
                while side/steps>remainder/4:
                    steps*=2
                    if steps>2**96:
                        break
                else:
                    kept=(length*steps/side).__floor__()*side/steps
                    if side/2<=kept<side and (best is None or kept/side>best[0]):
                        best=(kept/side,axis,lo+kept if keep_low else hi-kept)
    return None if best is None else best[1:]


def _definite_cut(record,component,face,normal,bounds,duration,arena,cache):
    """A cut at the certified one-sign boundary of the normal trace.

    Keeping one side of the rectangle along an axis, the largest dyadic part
    on which the exact Bernstein hull has one sign is found by bisection (a
    sub-rectangle's hull lies inside its parent's, so the test is monotone).
    That part needs no stream cap at all: its opposite stream is exactly
    zero and the actual moving-mask moment is the other one. The hull is
    wider than the range of a curved trace, so the part can end short of
    the sign curve.

    The cut makes two new corners, the ends of its edge. A moving boundary
    that passes a corner during the interval changes the shape of the mask
    in both rectangles at that instant, and each then spends temporal leaves
    on it. A constraint's whole-interval inner and outer lines are affine on
    this rectangle, so along the side a new corner lies on, the coordinates
    the constraint holds neither inside nor outside for the complete
    interval form one swept stretch. The coordinate moves TOWARDS the kept
    side, on the same dyadic grid, out of every stretch that ends inside the
    kept part; the shorter part is still one-sign. A stretch that reaches
    the kept end of that side is met by every cut keeping this part and
    moves nothing. A part of at least one eighth of the side is cut off, the
    largest first; the sign curve and whatever boundary crosses it stay in
    the remainder. Returns (axis, coordinate) or None; None defers to the
    midpoint across the largest variation. Exact polynomial and line
    arithmetic only, no leaf. The rule changes how many leaves a query
    needs, not the validity of its partition, and is not claimed to need no
    more leaves than bisection on every query.
    """
    from . import integration_differential_geometry as G
    with V._work((*normal.values(),*[q for pair in bounds for q in pair]),arena.resource):
        low,high=NM._bernstein_range(NM._unit_polynomial(normal,bounds))
    if low>=0 or high<=0:
        return None
    child=(*face[:4],bounds)
    lines=[]
    for name,sign in component['constraints']:
        box,offset=NM._posed_box(record['constraints'][name],duration,arena,cache)
        with V._work((*[q for pair in box for q in pair],offset,
                      *[q for vector in face[:3] for q in vector],
                      *[q for pair in bounds for q in pair]),arena.resource):
            lines.append(tuple(G._boxed_constraint_line(child,bounds,box,offset,sign,inner)
                               for inner in (True,False)))
    arena.work(64+128*len(lines))
    best,passes=None,0
    with V._work((*normal.values(),*[q for pair in lines for line in pair for q in line],
                  *[q for pair in bounds for q in pair]),arena.resource):
        for axis in range(2):
            lo,hi=bounds[axis];side=hi-lo
            for keep_low in (True,False):
                kept,step=Q(0),Q(1,2)
                for _ in range(40):
                    trial=kept+step
                    part=list(bounds)
                    part[axis]=(lo,lo+trial*side) if keep_low else (hi-trial*side,hi)
                    low,high=NM._bernstein_range(NM._unit_polynomial(normal,tuple(part)))
                    if low>=0 or high<=0:
                        kept=trial
                    step/=2
                # A stretch once left is never entered again, so every pass
                # that moves the coordinate leaves at least one for good.
                for _ in range(2*len(lines)+1):
                    if kept<Q(1,8):
                        break
                    at,toward=(lo+kept*side,-1) if keep_low else (hi-kept*side,1)
                    passes+=1;shift=Q(0)
                    for inner,outer in lines:
                        for other in bounds[1-axis]:
                            values=tuple(line[axis]*at+line[1-axis]*other+line[2] for line in (inner,outer))
                            if values[0]>=0 or values[1]<=0:
                                continue
                            # Fraction of the side to the nearest coordinate
                            # held inside or outside for the whole interval.
                            reach=[-value/(toward*line[axis]*side) for value,line in zip(values,(inner,outer))
                                   if toward*value*line[axis]<0]
                            if reach and min(reach)<kept:
                                shift=max(shift,min(reach))
                    if not shift:
                        break
                    kept=((kept-shift)*2**40).__floor__()/Q(2**40)
                if Q(1,8)<=kept<1 and (best is None or kept>best[0]):
                    best=(kept,axis,lo+kept*side if keep_low else hi-kept*side)
    arena.work(64+4*40*16*len(normal)+64*len(lines)*passes)
    return None if best is None else best[1:]


def integrate(record,component,layer,face,normal,polynomials,widths,duration,*,
              fallback,max_leaves,arena,cancel=None,_pose_cache=None):
    source_digest();_cancel(cancel)
    if (normal is None or polynomials or any(type(i) is not int or type(j) is not int or
            not 0<=i<=2 or not 0<=j<=2 for i,j in normal) or not TM._face_in_layer(face,layer)):
        return None
    if (duration<=0 or len(widths)!=2 or min(widths)<=0 or
            type(max_leaves) is not int or max_leaves<1):
        raise V.VolumeError('positive duration/stream widths and finite partition leaves required')
    cache=_PoseCache(arena) if _pose_cache is None else _pose_cache
    if cache.arena is not arena:
        raise V.VolumeError('partition requires its own query-local pose cache')
    target=min(widths);local_goal=target/8
    evaluations=0

    def evaluate(bounds,allowance,root=False):
        nonlocal evaluations
        _cancel(cancel);evaluations+=1
        child=(*face[:4],bounds)
        with _ScratchArena(arena) as scratch:
            old=fallback(bounds,Q(0),duration,0)
            answer=None
            if all(lo==hi for lo,hi in old):
                values,cost,method=old,1,'exact-geometric'
            else:
                if not root:
                    for helper,name in ((NM.integrate,'full-Q2'),(NM.integrate_near_signed,'signed-cap'),
                                        (NM.integrate_signed_complement,'complement')):
                        _cancel(cancel)
                        try:
                            kwargs={} if helper is NM.integrate else {'fallback':fallback}
                            answer=helper(record,component,layer,child,normal,(),(local_goal,)*2,duration,
                                max_leaves=min(64,allowance),arena=scratch,cancel=cancel,_pose_cache=cache,**kwargs)
                        except V.VolumeError as error:
                            # The finite analytic attempt cannot certify this
                            # rectangle; retain and refine the genuine bounds.
                            # Other scientific/resource/source failures escape.
                            if 'quadrature leaf ceiling' not in str(error):
                                raise
                            answer=None
                        if answer is not None:
                            values,cost,_=answer[:3];method=name
                            break
                if answer is None:
                    with V._work((*normal.values(),*[q for pair in bounds for q in pair],duration,local_goal),arena.resource):
                        low,high=NM._bernstein_range(NM._unit_polynomial(normal,bounds))
                        amplitude=max(abs(low),abs(high))
                        area=(bounds[0][1]-bounds[0][0])*(bounds[1][1]-bounds[1][0])
                        area_width=local_goal/amplitude if amplitude else area*duration
                    def signed_fallback(rect,a,b,level):
                        n,p=fallback(rect,a,b,level)[:2]
                        return ((p[0]-n[1],p[1]-n[0]),(Q(0),
                            (rect[0][1]-rect[0][0])*(rect[1][1]-rect[1][0])*(b-a)))
                    moments,cost,_=TM.integrate(record,component,layer,child,None,(normal,{(0,0):Q(1)}),
                        (local_goal,area_width),duration,
                        fallback=signed_fallback,max_leaves=1,arena=scratch,moments_only=True)
                    signed,occupied=moments
                    with V._work((*signed,*occupied,*[q for pair in old for q in pair],area,duration,low,high),arena.resource):
                        occupied=NM._intersection(occupied,(Q(0),area*duration))
                        values=NM._directed_from_signed(signed,old,*NM._occupied_stream_caps(low,high,signed,occupied))
                    method='signed-time-area'
            if not 1<=cost<=allowance:
                raise V.VolumeError('child quadrature exceeded the remaining global leaf allowance')
            arena.keep((*[q for pair in bounds for q in pair],*[q for pair in values for q in pair]),objects=12)
            return dict(bounds=bounds,values=values,cost=cost,method=method)

    active=[evaluate(face[4],max_leaves,True)]
    while True:
        _cancel(cancel)
        values,met,index=_aggregate(active,widths,arena)
        cost=sum(n['cost'] for n in active)
        if met or cost>=max_leaves:
            break
        parent=active[index];bounds=parent['bounds']
        remaining=max_leaves-(cost-parent['cost'])
        if remaining<2:
            break
        cut=_contained_cut(record,component,face,bounds,duration,arena,cache)
        if cut is None:
            cut=_definite_cut(record,component,face,normal,bounds,duration,arena,cache)
        if cut is None:
            axis=_split_axis(normal,bounds,arena)
            a,b=bounds[axis];middle=(a+b)/2
        else:
            axis,middle=cut
            a,b=bounds[axis]
        children=[]
        for k,span in enumerate(((a,middle),(middle,b))):
            child=list(bounds);child[axis]=span
            result=evaluate(tuple(child),remaining-(1 if k==0 else 0))
            children.append(result);remaining-=result['cost']
        # Never replace a covered parent by a partially evaluated pair.
        active[index:index+1]=children
    arena.keep((*[q for pair in values for q in pair],target,local_goal),objects=16+8*len(active))
    encoded_values=tuple(q for n in active for pair in (*n['bounds'],*n['values']) for q in pair)
    arena.work(32+16*len(active))
    # Retained output is charged in full; codec scratch needs only one row.
    arena.keep(encoded_values,objects=16+16*len(active))
    rectangles=[]
    for n in active:
        with V._work(tuple(q for pair in (*n['bounds'],*n['values']) for q in pair),arena.resource):
            rectangles.append(dict(coordinate_bounds_m=[list(map(V._encoded,p)) for p in n['bounds']],
                inward_bounds_m3=list(map(V._encoded,n['values'][0])),outward_bounds_m3=list(map(V._encoded,n['values'][1])),
                method=n['method'],leaves=n['cost']))
    certificate=dict(rectangles=rectangles,terminal_leaves=cost,evaluations=evaluations,
        pose_computations=cache.misses,pose_reuses=cache.hits,
        local_requested_width_m3=V._encoded(local_goal),
        relation='exact disjoint face partition; sum of certified directed intervals compared with original global widths',
        work_rule='all attempted child work on one caller arena; temporary proof scratch unwinds per child')
    source_digest();_cancel(cancel)
    return values,cost,met,certificate
