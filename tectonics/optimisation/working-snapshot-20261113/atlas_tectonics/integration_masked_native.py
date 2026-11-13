"""Proved full-face Q2 streams and signed moving-mask moment identities.

This is a numerical helper for the issued component-wall producer, NOT an
ownership issuer. The full-face route returns None for a genuinely clipped or
uncertain face. A separate near-signed route can retain that actual moving
mask, integrate the signed Q2 moment, and bound its nonzero opposite stream
using exact Bernstein coefficients. Neither point sampling nor a positive-area
estimate licenses full-face coverage or deletion of a small polynomial term.
A one-sign complement certificate can also prove that one full-face stream
survives unchanged, while retaining the other through the signed mask moment.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from math import comb
import hashlib
from pathlib import Path

from . import integration_volume as V
from . import integration_wall_measures as W
from . import integration_native_projection as NP
from .regional_heat3d import _cancel

METHOD='proved-full-interval-component-face:exact-chart-Q2-directed-v1'
SIGNED_METHOD='moving-mask-signed-Q2-moment:exact-Bernstein-opposite-stream-cap-v1'
COMPLEMENT_METHOD='moving-mask-signed-Q2-moment:proved-one-sign-complement-v1'
_LOADED=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_PROJECTION_LOADED=hashlib.sha256(Path(NP.__file__).read_bytes()).hexdigest()


def source_digest():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=_LOADED:
        raise V.VolumeError('full-face native integration source changed after loading')
    if hashlib.sha256(Path(NP.__file__).read_bytes()).hexdigest()!=_PROJECTION_LOADED:
        raise V.VolumeError('native directed projection source changed after loading')
    from .integration_moving_face_moments import source_digest as geometry_digest
    from .integration_q2_directed import source_digest as quadrature_digest
    return hashlib.sha256((_LOADED+_PROJECTION_LOADED+geometry_digest()+quadrature_digest()).encode('ascii')).hexdigest()


def _unit_polynomial(polynomial, bounds):
    out={};(a,b),(c,d)=bounds
    for (i,j),value in polynomial.items():
        for k in range(i+1):
            for l in range(j+1):
                key=k,l
                out[key]=out.get(key,Q(0))+value*comb(i,k)*a**(i-k)*(b-a)**k*comb(j,l)*c**(j-l)*(d-c)**l
    return {key:value for key,value in out.items() if value}


def _bernstein_range(polynomial):
    """Exact tensor-Q2 convex-hull enclosure on the unit square."""
    coefficients=tuple(sum((value*Q(comb(k,i),comb(2,i))*Q(comb(l,j),comb(2,j))
        for (i,j),value in polynomial.items() if i<=k and j<=l),Q(0))
        for k in range(3) for l in range(3))
    return min(coefficients),max(coefficients)


def _intersection(*pairs):
    pair=max(value[0] for value in pairs),min(value[1] for value in pairs)
    if pair[0]>pair[1]:
        raise V.VolumeError('signed native moment contradicts directed physical enclosure')
    return pair


def _occupied_stream_caps(low, high, signed, occupied):
    """Caps of N=int max(0,-p) and P=int max(0,p) over the ACTUAL occupied measure.

    ``[low,high]`` encloses p on the rectangle, ``signed`` its integral over
    the moving mask and ``occupied`` the mask's own time-area. Two certified
    bounds use that measure, and not the whole rectangle for the whole time:
    the amplitude bound ``max(0,-low) O`` (and ``max(0,high) O``), and the
    chord of the convex positive part between the two ends of the range,
    ``max(0,x) <= high (x-low)/(high-low)``, integrated over the mask:
    ``P <= high (S-low O)/(high-low)`` and ``N <= -low (high O-S)/(high-low)``.
    The chord is attained only when p takes the two end values of the range
    on the mask. When the range has one sign the opposite cap is exactly
    zero and the chord is not used. Each bound is evaluated at the end of
    the enclosures that makes it largest.
    """
    measure=occupied[1]
    negative,positive=max(Q(0),-low)*measure,max(Q(0),high)*measure
    if low<0<high:
        negative=min(negative,-low*(high*measure-signed[0])/(high-low))
        positive=min(positive,high*(signed[1]-low*measure)/(high-low))
    return max(Q(0),negative),max(Q(0),positive)


def _directed_from_signed(signed, original, negative_cap, positive_cap):
    """Correlated P-N=S, not an assertion that interval endpoints coincide."""
    negative=_intersection(original[0],(Q(0),negative_cap))
    positive=_intersection(original[1],(Q(0),positive_cap))
    for _ in range(2):
        negative=_intersection(negative,(positive[0]-signed[1],positive[1]-signed[0]))
        positive=_intersection(positive,(negative[0]+signed[0],negative[1]+signed[1]))
    return negative,positive


def _posed_box(constraint,duration,arena,cache):
    from . import integration_differential_geometry as G
    return (G._constraint_boxes(constraint,Q(0),duration,128,arena) if cache is None else
            cache.boxes(constraint,Q(0),duration,128,arena))


def _outer_stream_caps(record,component,face,polynomial,duration,arena,cancel,_pose_cache=None):
    """A single whole-time OUTER polygon contains every actual moving mask."""
    from . import integration_differential_geometry as G
    outer=W._rectangle(face[4])
    for name,sign in component['constraints']:
        _cancel(cancel)
        normal,offset=_posed_box(record['constraints'][name],duration,arena,_pose_cache)
        with V._work((*[q for pair in normal for q in pair],offset,
                      *[q for vector in face[:3] for q in vector],
                      *[q for pair in face[4] for q in pair]),arena.resource):
            line=G._boxed_constraint_line(face,face[4],normal,offset,sign,False)
            outer=W._clip2(outer,line,arena)
        if not outer:
            break
    arena.work(128+128*len(polynomial))
    area=W._integral(outer,(Q(0),Q(0),Q(1)),arena)
    if area<0:
        raise V.VolumeError('component outer polygon has negative area')
    bounds=(tuple((min(p[j] for p in outer),max(p[j] for p in outer)) for j in range(2))
            if area else ((Q(0),Q(0)),)*2)
    with V._work((*polynomial.values(),*[q for pair in bounds for q in pair],area,duration),arena.resource):
        low,high=_bernstein_range(_unit_polynomial(polynomial,bounds)) if area else (Q(0),Q(0))
        negative,positive=max(Q(0),-low)*area*duration,max(Q(0),high)*area*duration
        arena.keep((*[q for point in outer for q in point],*[q for pair in bounds for q in pair],
                    area,low,high,negative,positive),objects=20+4*len(outer))
        certificate=dict(kind='whole-time-outer-halfplane-intersection',
            polygon_m=[list(map(V._encoded,p)) for p in outer],
            enclosing_coordinate_bounds_m=[list(map(V._encoded,pair)) for pair in bounds],
            area_m2=V._encoded(area),local_Bernstein_range_m_s=list(map(V._encoded,(low,high))),
            proof_leaves=1,empty_area=area==0)
    return negative,positive,certificate


def _signed_complement(record,component,face,polynomial,duration,arena,cancel,_pose_cache=None):
    """Two exact midpoint slabs: contained, or one common polynomial sign.

    Trying both chart axes is a bounded predicate, not geometric sampling.
    The selected two slabs cover the entire face, so their certified sign
    encloses EVERY possibly omitted point throughout the complete interval.
    """
    from . import integration_differential_geometry as G
    arena.keep((),objects=8+2*len(component['constraints']))
    posed=[]
    for name,sign in component['constraints']:
        _cancel(cancel)
        normal,offset=_posed_box(record['constraints'][name],duration,arena,_pose_cache)
        arena.keep((*[q for pair in normal for q in pair],offset),objects=4)
        posed.append((name,sign,normal,offset))
    for axis in range(2):
        lo,hi=face[4][axis];middle=(lo+hi)/2
        slabs=[]
        for limits in ((lo,middle),(middle,hi)):
            _cancel(cancel);arena.work(128+64*len(posed)+128*len(polynomial))
            bounds=list(face[4]);bounds[axis]=limits;bounds=tuple(bounds)
            arena.keep(tuple(q for pair in bounds for q in pair),objects=8)
            margins=[]
            for name,sign,normal,offset in posed:
                with V._work((*[q for pair in normal for q in pair],offset,
                              *[q for vector in face[:3] for q in vector],
                              *[q for pair in bounds for q in pair]),arena.resource):
                    line=G._boxed_constraint_line(face,bounds,normal,offset,sign,True)
                    margin=min(line[0]*u+line[1]*v+line[2] for u,v in W._rectangle(bounds))
                arena.keep((margin,),objects=1)
                margins.append((name,sign,margin))
            low,high=_bernstein_range(_unit_polynomial(polynomial,bounds))
            arena.keep((low,high),objects=1)
            slabs.append((bounds,all(margin>=0 for _,_,margin in margins),low,high,margins))
        for omitted_sign in (-1,1):
            if all(inside or (high<=0 if omitted_sign<0 else low>=0)
                   for _,inside,low,high,_ in slabs):
                # Actual rational widths cover the encoded certificate too;
                # names refer to already owned support strings. No quadratic
                # worst-case record expansion is reserved or retained.
                arena.keep(tuple(q for bounds,_,low,high,margins in slabs
                    for q in (*[v for pair in bounds for v in pair],low,high,*[v for _,_,v in margins])),
                    objects=24+8*len(posed))
                return dict(axis=axis,omitted_polynomial_sign=omitted_sign,slabs=[dict(
                    coordinate_bounds_m=[list(map(V._encoded,pair)) for pair in bounds],
                    wholly_contained=inside,
                    whole_slab_Bernstein_range_m_s=list(map(V._encoded,(low,high))),
                    constraint_minima=[dict(name=name,sign=sign,minimum=V._encoded(margin))
                                       for name,sign,margin in margins])
                    for bounds,inside,low,high,margins in slabs])
    return None


def integrate_signed_complement(record,component,layer,face,normal_polynomial,polynomials,widths,duration,
                                *,fallback,max_leaves,arena,cancel=None,_pose_cache=None):
    """Keep an unchanged full-face stream when only the other sign is cut.

    If the complement has p<=0, P_mask=P_face and N_mask=P_face-S_mask.
    The reversed case is symmetric. No claim of full material coverage is
    made. Both exact proof slabs, full-face quadrature and signed temporal
    leaves share the original leaf ceiling; each numerical stage receives
    half the original stream width. Failed premises return None.
    """
    from . import integration_moving_face_moments as TM
    source_digest();_cancel(cancel)
    if normal_polynomial is None or any(type(i) is not int or type(j) is not int or
        not 0<=i<=2 or not 0<=j<=2 for i,j in normal_polynomial):
        return None
    if duration<=0 or len(widths)!=2+len(polynomials):
        raise V.VolumeError('positive interval and complete component moment widths required')
    if max_leaves<4 or min(widths[:2])<=0 or not TM._face_in_layer(face,layer):
        return None
    (a,b),(c,d)=face[4]
    with V._work((*normal_polynomial.values(),*(q for p in polynomials for q in p.values()),
                  a,b,c,d,duration,*widths),arena.resource):
        certificate=_signed_complement(record,component,face,normal_polynomial,duration,arena,cancel,_pose_cache)
        if certificate is None:
            return None
        stage_width=min(widths[:2])/2
        full=NP._directed_q2_bounds(_unit_polynomial(normal_polynomial,face[4]),
            (b-a)*(d-c)*duration,max_width=stage_width,max_leaves=max_leaves-3,
            budget=arena.resource,cancel=cancel,_arena=arena if _pose_cache is not None else None)
        arena.keep((*full['positive_volume_bounds_m3'],*full['negative_volume_bounds_m3'],
                    full['positive_volume_m3'],full['negative_volume_m3'],full['signed_volume_m3']),objects=12)
        _cancel(cancel)
        original=fallback(face[4],Q(0),duration,0)
        def signed_fallback(bounds,start,end,level):
            values=(original if bounds==face[4] and start==0 and end==duration and level==0
                    else fallback(bounds,start,end,level))
            inward,outward=values[:2]
            return ((outward[0]-inward[1],outward[1]-inward[0]),*values[2:])
        result=TM.integrate(record,component,layer,face,None,(normal_polynomial,*polynomials),
            (stage_width,*widths[2:]),duration,fallback=signed_fallback,
            max_leaves=max_leaves-2-full['leaves'],arena=arena,moments_only=True)
        if result is None:
            return None
        moments,temporal_leaves,_=result
        arena.keep(tuple(q for pair in moments for q in pair),objects=4+len(moments))
        signed=moments[0]
        if certificate['omitted_polynomial_sign']<0:
            positive=_intersection(full['positive_volume_bounds_m3'],original[1],(Q(0),original[1][1]))
            negative=_intersection((positive[0]-signed[1],positive[1]-signed[0]),original[0],(Q(0),original[0][1]))
        else:
            negative=_intersection(full['negative_volume_bounds_m3'],original[0],(Q(0),original[0][1]))
            positive=_intersection((negative[0]+signed[0],negative[1]+signed[1]),original[1],(Q(0),original[1][1]))
        values=(negative,positive,*moments[1:])
        leaves=2+full['leaves']+temporal_leaves
        arena.keep((*signed,*positive,*negative,stage_width),objects=24)
        certificate.update(signed_moment_bounds_m3=list(map(V._encoded,signed)),
            full_face_positive_bounds_m3=list(map(V._encoded,full['positive_volume_bounds_m3'])),
            full_face_negative_bounds_m3=list(map(V._encoded,full['negative_volume_bounds_m3'])),
            per_stage_width_m3=V._encoded(stage_width),proof_leaves=2,
            full_face_leaves=full['leaves'],temporal_leaves=temporal_leaves,
            relation='unchanged opposite-sign full-face stream; P-N lies in the actual signed-mask interval')
    source_digest();_cancel(cancel)
    return values,leaves,all(hi-lo<=width for (lo,hi),width in zip(values,widths)),certificate


def integrate_near_signed(record,component,layer,face,normal_polynomial,polynomials,widths,duration,
                          *,fallback,max_leaves,arena,cancel=None,_pose_cache=None):
    """Actual signed moving-mask Q2 plus a rigorous small opposite-flow cap.

    The entire fixed face bounds the unknown occupied subset. Thus if its
    polynomial Bernstein range is [l,h], P <= A*dt*max(h,0) and
    N <= A*dt*max(-l,0). Only when one cap fits the ORIGINAL stream widths do
    we spend the remaining width on S=integral(p). No coefficient, tiny lobe,
    physical support or tolerance is removed. General sign-changing traces
    with a larger whole-face cap can use a certified outer mask polygon.
    Its bounding rectangle encloses the velocity range while its actual area
    caps the measure. The actual moving mask still supplies the signed moment.
    """
    from . import integration_moving_face_moments as TM
    source_digest();_cancel(cancel)
    if normal_polynomial is None or any(type(i) is not int or type(j) is not int or
        not 0<=i<=2 or not 0<=j<=2 for i,j in normal_polynomial):
        return None
    if duration<=0 or len(widths)!=2+len(polynomials):
        raise V.VolumeError('positive interval and complete component moment widths required')
    if not TM._face_in_layer(face,layer):
        return None
    (a,b),(c,d)=face[4]
    with V._work((*normal_polynomial.values(),*(q for p in polynomials for q in p.values()),
                  a,b,c,d,duration,*widths),arena.resource):
        arena.work(256+128*len(normal_polynomial))
        low,high=_bernstein_range(_unit_polynomial(normal_polynomial,face[4]))
        measure=(b-a)*(d-c)*duration
        negative_cap,positive_cap=max(Q(0),-low)*measure,max(Q(0),high)*measure
        cap=min(negative_cap,positive_cap)
        outer_certificate=None
        proof_leaves=0
        if cap>=min(widths[:2]):
            if max_leaves<2:
                return None
            negative_cap,positive_cap,outer_certificate=_outer_stream_caps(
                record,component,face,normal_polynomial,duration,arena,cancel,_pose_cache)
            cap=min(negative_cap,positive_cap)
            if cap>=min(widths[:2]):
                return None
            proof_leaves=1
        # The dominant stream inherits both cap uncertainty and signed-moment
        # uncertainty. The smaller stream is enclosed by its cap directly.
        signed_width=min(widths[:2])-cap
        original=fallback(face[4],Q(0),duration,0)
        nonzero=any(normal_polynomial.values())
        def signed_fallback(bounds,start,end,level):
            values=(original if bounds==face[4] and start==0 and end==duration and level==0
                    else fallback(bounds,start,end,level))
            inward,outward=values[:2]
            # N=P=0 exactly makes p vanish almost everywhere on the mask. A
            # polynomial that is not identically zero vanishes only on a null
            # set of the face, so the mask has no time-area on this leaf.
            # Otherwise only the whole rectangle for the whole leaf bounds it.
            absent=nonzero and not any((*inward,*outward))
            return ((outward[0]-inward[1],outward[1]-inward[0]),
                    (Q(0),Q(0) if absent else (bounds[0][1]-bounds[0][0])*(bounds[1][1]-bounds[1][0])*(end-start)),
                    *values[2:])
        occupied=None
        if outer_certificate is not None and outer_certificate['empty_area']:
            result=(tuple(_intersection((Q(0),Q(0)),pair)
                for pair in (signed_fallback(face[4],Q(0),duration,0)[0],
                             *signed_fallback(face[4],Q(0),duration,0)[2:])),0,True)
        else:
            # The mask's own time-area is passive: it is enclosed on the
            # temporal leaves that the signed and requested moments select,
            # and takes no part in the exact-leaf test or the bisection order.
            # Its width limit is the whole measure, which it cannot exceed,
            # so the leaves are those of the call without it.
            result=TM.integrate(record,component,layer,face,None,(normal_polynomial,{(0,0):Q(1)},*polynomials),
                (signed_width,measure,*widths[2:]),duration,fallback=signed_fallback,
                max_leaves=max_leaves-proof_leaves,arena=arena,moments_only=True,passive=(1,))
            if result is not None:
                occupied=_intersection(result[0][1],(Q(0),measure))
                result=((result[0][0],*result[0][2:]),*result[1:])
        if result is None:
            return None
        moments,leaves,_=result
        if occupied is not None:
            tighter=_occupied_stream_caps(low,high,moments[0],occupied)
            negative_cap,positive_cap=min(negative_cap,tighter[0]),min(positive_cap,tighter[1])
        streams=_directed_from_signed(moments[0],original,negative_cap,positive_cap)
        values=(*streams,*moments[1:])
        certificate=dict(signed_moment_bounds_m3=list(map(V._encoded,moments[0])),
            whole_face_Bernstein_range_m_s=list(map(V._encoded,(low,high))),
            negative_stream_cap_m3=V._encoded(negative_cap),positive_stream_cap_m3=V._encoded(positive_cap),
            signed_moment_width_limit_m3=V._encoded(signed_width),
            relation='P-N lies in the signed-moment interval; directed endpoints are correlated, not an exact signed value')
        if occupied is not None:
            certificate['occupied_time_area_bounds_m2_s']=list(map(V._encoded,occupied))
        if outer_certificate is not None:
            arena.keep((*moments[0],negative_cap,positive_cap,signed_width),objects=20)
            certificate['outer_support_enclosure']=outer_certificate
            leaves+=proof_leaves
    source_digest();_cancel(cancel)
    return values,leaves,all(hi-lo<=width for (lo,hi),width in zip(values,widths)),certificate


def integrate(record,component,layer,face,normal_polynomial,polynomials,widths,duration,
              *,max_leaves,arena,cancel=None,_pose_cache=None):
    """Return (inward/outward/moment bounds, leaves, met), or None.

    The caller retains its actual typed support/component authority and emits
    the issued record. Widths, dimensional chart and complete interval are
    unchanged. All geometric predicates and Q2 work use the same WorkBudget.
    """
    from . import integration_differential_geometry as G
    from .integration_moving_face_moments import _face_in_layer
    source_digest();_cancel(cancel)
    if normal_polynomial is None:
        return None
    # This route integrates tensor Q2, not a truncation of a general polynomial.
    # The caller's original general-degree enclosure remains the fallback.
    if any(type(i) is not int or type(j) is not int or not 0<=i<=2 or not 0<=j<=2
           for i,j in normal_polynomial):
        return None
    if duration<=0 or len(widths)!=2+len(polynomials):
        raise V.VolumeError('positive interval and complete component moment widths required')
    if not _face_in_layer(face,layer):
        return None
    rectangle=W._rectangle(face[4])
    for name,sign in component['constraints']:
        _cancel(cancel)
        normal,offset=_posed_box(record['constraints'][name],duration,arena,_pose_cache)
        inner=G._boxed_constraint_line(face,face[4],normal,offset,sign,True)
        arena.work(64)
        if any(inner[0]*u+inner[1]*v+inner[2]<0 for u,v in rectangle):
            return None
    # Every half-plane contains the WHOLE rectangle for ALL times, and the
    # radial test uses its true interior minimum, not just its corner radii.
    (a,b),(c,d)=face[4]
    area=(b-a)*(d-c)
    with V._work((*normal_polynomial.values(),*(q for p in polynomials for q in p.values()),
                  a,b,c,d,duration,*widths),arena.resource):
        normal=_unit_polynomial(normal_polynomial,face[4])
        streams=NP._directed_q2_bounds(normal,area*duration,max_width=min(widths[:2]),
            max_leaves=max_leaves,budget=arena.resource,cancel=cancel,
            _arena=arena if _pose_cache is not None else None)
        values=[streams['negative_volume_bounds_m3'],streams['positive_volume_bounds_m3']]
        for polynomial in polynomials:
            _cancel(cancel);arena.work(32+16*len(polynomial))
            value=duration*sum((coefficient*(b**(i+1)-a**(i+1))/Q(i+1)*
                               (d**(j+1)-c**(j+1))/Q(j+1)
                               for (i,j),coefficient in polynomial.items()),Q(0))
            values.append((value,value))
    source_digest();_cancel(cancel)
    return tuple(values),streams['leaves'],all(hi-lo<=w for (lo,hi),w in zip(values,widths))
