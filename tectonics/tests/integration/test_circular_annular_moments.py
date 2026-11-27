"""One-pass annular disk moments equal two independent single-disk passes.

The reference below is the single-radius loop the one-pass form replaced,
kept verbatim apart from names. Results, work units and reserved peak must
match coefficient for coefficient.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from pathlib import Path
import types
import unittest

from atlas_tectonics.integration.geometry import circular_moments as C
from atlas_tectonics.integration.geometry.moving_face_moments import _Jets, _Branch
from atlas_tectonics.integration.geometry.volume_bounds import _Arena
from atlas_tectonics.integration.resources import WorkBudget


def _old_roots(a,b,r2,J):
    d=tuple(J.sub(y,x) for x,y in zip(a,b))
    A=C._dot(d,d,J)
    if A==J.z:
        return None
    if A[0][0]<=0:
        raise _Branch()
    B=J.scale(C._dot(a,d,J),2)
    c=J.sub(C._dot(a,a,J),J.constant(r2))
    D=J.sub(J.mul(B,B),J.scale(J.mul(A,c),4))
    if D==J.z or D[0][1]<0:
        return None
    if D[0][0]<=0:
        raise _Branch()
    if c==J.z:
        return C._ordered(J.z,J.div(J.neg(B),A),J)
    if J.sub(C._dot(b,b,J),J.constant(r2))==J.z:
        return C._ordered(J.constant(1),J.div(c,A),J)
    root=C._sqrt(D,J);denominator=J.scale(A,2)
    return J.div(J.sub(J.neg(B),root),denominator),J.div(J.add(J.neg(B),root),denominator)


def _old_first_moments(polygon,radius_squared,J,arena,*,fixed_axis_coordinates=None):
    r2=Q(radius_squared)
    if r2<=0 or len(polygon)<3:
        return J.z,J.z
    order=len(J.z)-1
    with C._rectangle_coordinate_jets(polygon,fixed_axis_coordinates,J,arena) as polygon, \
            arena.resource.reserve(65536+384*(order+1)**2,category='circular-first-moment-jets'):
        radius=C._sqrt(J.constant(r2),J)
        total=[J.z,J.z]

        def add(values):
            for i,value in enumerate(values):
                total[i]=J.add(total[i],value)

        def project(point,on_circle):
            if on_circle:
                return point
            scale=J.div(radius,C._sqrt(C._dot(point,point,J),J))
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
            if (C._dot(a,a,J)[0][1] <= r2 and C._dot(b,b,J)[0][1] <= r2):
                line(a,b)
                continue
            if C._segment_box_outside(a,b,r2,arena):
                arc(a,b)
                continue
            roots=_old_roots(a,b,r2,J)
            if roots is None:
                arc(a,b)
                continue
            try:
                lo,lo_circle=C._clamp_root(roots[0],J)
                hi,hi_circle=C._clamp_root(roots[1],J)
            except _Branch:
                arena.work(32*(order+1)**2)
                positions=C._endpoint_root_positions(a,b,r2,roots,J)
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
    return tuple(total)


J=_Jets()


def _jet(value,rate=0):
    return J.add(J.constant(value),(J.zero,J.I.point(rate))+(J.zero,)*(len(J.z)-2)) if rate else J.constant(value)


def _moving(*points):
    return tuple((_jet(x,vx),_jet(y,vy)) for x,y,vx,vy in points)


def _tagged_square(h):
    return tuple((J.constant(u),J.constant(v),frozenset((('rectangle',0,int(u>0)),('rectangle',1,int(v>0)))))
                 for u,v in ((-h,-h),(h,-h),(h,h),(-h,h)))


_SQUARE=Q(3,2)
CASES={
    'inside both': (_moving((Q(1,10),0,Q(1,100),0),(Q(3,10),0,0,Q(1,50)),(0,Q(3,10),Q(-1,100),0)),4,1,None),
    'crossing outer only': (_moving((Q(3,2),0,Q(1,100),0),(3,0,0,Q(1,100)),(Q(3,2),Q(1,2),0,0)),4,Q(1,100),None),
    'crossing both': (_moving((-3,Q(-1,5),Q(1,100),0),(3,Q(-1,5),0,Q(1,50)),(0,3,Q(-1,100),0)),4,1,None),
    'rectangle tags': (_tagged_square(_SQUARE),4,1,((-_SQUARE,_SQUARE),(-_SQUARE,_SQUARE))),
    'outer radius zero': (_moving((-3,Q(-1,5),0,0),(3,Q(-1,5),0,0),(0,3,0,0)),0,1,None),
}


def _run(compute):
    budget=WorkBudget(1<<34)
    with _Arena(budget) as arena:
        result=compute(arena)
        return result,arena.work_units,budget.peak_reserved_bytes


def _two_calls(polygon,outer,inner,fixed,arena):
    return (_old_first_moments(polygon,outer,J,arena,fixed_axis_coordinates=fixed),
            _old_first_moments(polygon,inner,J,arena,fixed_axis_coordinates=fixed))


class AnnularFirstMoments(unittest.TestCase):
    def test_equal_to_two_single_disk_passes(self):
        for name,(polygon,outer,inner,fixed) in CASES.items():
            with self.subTest(name):
                expected=_run(lambda arena:_two_calls(polygon,outer,inner,fixed,arena))
                actual=_run(lambda arena:C.annular_first_moments(polygon,outer,inner,J,arena,
                                                                  fixed_axis_coordinates=fixed))
                self.assertEqual(actual,expected)
                self.assertNotEqual(expected[0],((J.z,J.z),(J.z,J.z)))

    def test_branch_is_raised_by_both(self):
        # Overlapping endpoint enclosures leave the edge length sign unproved.
        wide=lambda lo,hi:((J.I.point(lo)[0],J.I.point(hi)[1]),)+(J.zero,)*(len(J.z)-1)
        polygon=((wide(Q(19,10),Q(21,10)),J.z),(wide(Q(39,20),Q(41,20)),J.z),(J.z,J.constant(Q(1,2))))
        for compute in (lambda arena:_two_calls(polygon,4,1,None,arena),
                        lambda arena:C.annular_first_moments(polygon,4,1,J,arena)):
            with self.assertRaises(_Branch):
                _run(compute)

    def test_vertex_table_mutant_is_killed(self):
        # A table entry reused for another vertex must change a result.
        source=Path(C.__file__).read_text(encoding='utf-8')
        old='dots[i]=_dot(points[i],points[i],J)'
        self.assertEqual(source.count(old),1)
        mutant=types.ModuleType('circular_moments_mutant')
        mutant.__dict__.update(__file__=C.__file__,__package__=C.__package__)
        exec(compile(source.replace(old,'dots[i]=_dot(points[i-1],points[i-1],J)'),C.__file__,'exec'),
             mutant.__dict__)
        polygon,outer,inner,fixed=CASES['crossing both']
        expected=_run(lambda arena:_two_calls(polygon,outer,inner,fixed,arena))[0]
        killed=_run(lambda arena:mutant.annular_first_moments(polygon,outer,inner,J,arena))[0]
        self.assertNotEqual(killed,expected)


if __name__=='__main__':
    unittest.main()
