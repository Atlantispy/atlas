"""Targeted W01 stage-2 regressions from the independent double-check.

The original 13 review probes are retained below. Added adversarial tests compare
short finite arcs with Decimal geometry of the actual captured endpoint bytes,
not the same floating implementation or an enlarged boundary band. Tolerances
come from the existing geometry fixture. No timing limits or geological claims.
"""
from pathlib import Path
import sys,math,json,unittest,threading,copy
import numpy as np
import shapely
from decimal import Decimal, localcontext
from atlas_tectonics.coordinates import SphericalFrame
from atlas_tectonics.geometry import PlanarGeometry as PG, GeometryError, GeometryLimits
from atlas_tectonics.spherical_geometry import SphericalChart, SphericalGeometry as SG
from atlas_tectonics.geometry_index import GeometryIndex,GeometryFeature,audit_coverage
from atlas_tectonics.resources import WorkBudget
from concurrent.futures import CancelledError


def small_trace():
    c=np.array([1.,1.,1.]);c/=np.linalg.norm(c)
    t=np.array([1.,-1.,0.]);t/=np.linalg.norm(t)
    chart=SphericalChart(SphericalFrame(1.,'independent'),tuple(c))
    angle=1e-8
    ends=np.array([math.cos(angle)*c-math.sin(angle)*t,math.cos(angle)*c+math.sin(angle)*t])
    return SG.polyline(ends,chart=chart),c


class ReportedStage2Regressions(unittest.TestCase):
    def test_short_arc_distance_within_declared_angular_tolerance(self):
        feature,c=small_trace()
        # Reference uses exact floating endpoint values at 80 decimal digits.
        # The chosen symmetric query projects strictly within the short arc.
        a=np.frombuffer(feature._segments_start,dtype=np.float64)
        b=np.frombuffer(feature._segments_end,dtype=np.float64)
        with localcontext() as ctx:
            ctx.prec=80
            aa=list(map(lambda x:Decimal.from_float(float(x)),a));bb=list(map(lambda x:Decimal.from_float(float(x)),b))
            pp=list(map(lambda x:Decimal.from_float(float(x)),c))
            normal=[aa[1]*bb[2]-aa[2]*bb[1],aa[2]*bb[0]-aa[0]*bb[2],aa[0]*bb[1]-aa[1]*bb[0]]
            ratio=abs(sum(x*y for x,y in zip(pp,normal)))/(sum(x*x for x in pp)*sum(x*x for x in normal)).sqrt()
            expected=math.asin(float(ratio))
        actual=float(feature.distance_to(c)[()])
        self.assertLessEqual(abs(actual-expected),2e-12,(actual,expected))

    def test_short_arc_corridor_keeps_its_midpoint(self):
        f,c=small_trace()
        self.assertTrue(bool(f.within_distance(c,2e-12)),float(f.distance_to(c)))

    def test_short_arc_boundary_band(self):
        f,c=small_trace()
        self.assertEqual(int(f.classify(c,angular_tolerance_rad=2e-12)),0)

    def test_short_arc_index_keeps_boundary_candidate(self):
        f,c=small_trace()
        with GeometryIndex((GeometryFeature('trace',f),)) as index:
            self.assertEqual(index.query(c,angular_tolerance_rad=2e-12).pairs.tolist(),[[0,0]])

    def test_spherical_out_of_range_distance_refused_not_infinity(self):
        chart=SphericalChart(SphericalFrame(1e308,'extreme'),(1.,0.,0.))
        a=.1
        f=SG.polyline([[math.cos(a),-math.sin(a),0],[math.cos(a),math.sin(a),0]],chart=chart)
        try:
            out=f.distance_to([[-1.,0.,0.]])
        except GeometryError:
            return
        self.assertTrue(np.isfinite(out).all(),out.tolist())

    def test_constructor_and_wkb_zero_edge_validation_agree(self):
        vertices=[[0.,0.],[1.,0.],[1.,0.],[2.,0.]]
        with self.assertRaises(GeometryError):PG.polyline(vertices,frame_id='p')
        raw=shapely.to_wkb(shapely.LineString(vertices),byte_order=1)
        with self.assertRaises(GeometryError):PG.from_wkb(raw,frame_id='p')

    def test_random_finite_planar_segment_distance(self):
        rng=np.random.default_rng(99173)
        vertices=np.array([[0.,0.],[1.,2.],[3.,2.],[4.,-1.]])
        p=PG.polyline(vertices,frame_id='p');queries=rng.uniform(-2,6,(400,2))
        expect=[]
        for q in queries:
            ds=[]
            for a,b in zip(vertices[:-1],vertices[1:]):
                v=b-a;t=min(1.,max(0.,float((q-a)@v/(v@v))))
                ds.append(math.hypot(*(q-(a+t*v))))
            expect.append(min(ds))
        np.testing.assert_allclose(p.distance_to(queries),expect,atol=1e-12,rtol=1e-12)

    def test_random_spherical_rectangles_analytic_solid_angle(self):
        rng=np.random.default_rng(234012)
        for i in range(80):
            chart=SphericalChart(SphericalFrame(2.,'r'),tuple(rng.normal(size=3)))
            x0,x1=sorted(rng.uniform(-2,2,2));y0,y1=sorted(rng.uniform(-2,2,2))
            xy=np.array([[x0,y0],[x1,y0],[x1,y1],[x0,y1]])
            # Independent construction using orthogonal basis and normalisation.
            directions=np.column_stack([xy,np.ones(4)])@chart.basis
            p=SG.polygon(directions,chart=chart)
            f=lambda x,y:math.atan2(x*y,math.sqrt(1+x*x+y*y))
            expected=f(x1,y1)-f(x0,y1)-f(x1,y0)+f(x0,y0)
            self.assertLess(abs(p.area_steradians-expected),2e-12)

    def test_random_planar_index_exhaustive_all_hits(self):
        rng=np.random.default_rng(7602)
        features=[]
        for i in range(45):
            a=rng.uniform(-5,5,2);b=a+rng.uniform(.1,2,2)
            features.append(GeometryFeature(f'{i:03}',PG.polygon([a,[b[0],a[1]],b,[a[0],b[1]]],frame_id='p')))
        points=rng.uniform(-5,7,(400,2))
        expected=sorted((int(j),i) for i,f in enumerate(features) for j in np.flatnonzero(f.geometry.classify(points)>=0))
        with GeometryIndex(features) as tree:self.assertEqual(tree.query(points).pairs.tolist(),[list(p) for p in expected])

    def test_coverage_explicit_gap_overlap_and_contacts(self):
        box=lambda a,b:PG.polygon([[a,0],[b,0],[b,1],[a,1]],frame_id='p')
        domain=box(0,3)
        valid=audit_coverage(domain,[GeometryFeature('a',box(0,1)),GeometryFeature('b',box(1,3))])
        self.assertTrue(valid.complete);self.assertEqual(len(valid.contacts),1)
        gap=audit_coverage(domain,[GeometryFeature('a',box(0,1)),GeometryFeature('b',box(2,3))])
        self.assertEqual(gap.gap_area_m2,1.)
        overlap=audit_coverage(domain,[GeometryFeature('a',box(0,2)),GeometryFeature('b',box(1,3))])
        self.assertFalse(overlap.complete);self.assertEqual(overlap.overlaps[0][2].area_m2,1.)

    def test_negative_hemisphere_is_outside_not_projected_back(self):
        ch=SphericalChart(SphericalFrame(1.,'s'),(0.,0.,1.))
        p=SG.polygon([[-.2,-.2,1],[.2,-.2,1],[.2,.2,1],[-.2,.2,1]],chart=ch)
        np.testing.assert_array_equal(p.classify([[0,0,1],[0,0,-1]]),[1,-1])

    def test_public_geometry_immutability_and_retained_budget_release(self):
        p=PG.polygon([[0,0],[1,0],[1,1],[0,1]],frame_id='p');b=WorkBudget(8<<20)
        with GeometryIndex((GeometryFeature('one',p),),budget=b) as tree:
            self.assertGreater(b.reserved_bytes,0)
            hits=tree.query([[.5,.5]])
            with self.assertRaises(ValueError):hits.pairs.setflags(write=True)
            self.assertIs(copy.deepcopy(p),p)
        self.assertEqual(b.reserved_bytes,0)

    def test_empty_geometry_cancellation_agrees_with_nonempty(self):
        from threading import Event
        ch=SphericalChart(SphericalFrame(1.,'s'),(0.,0.,1.))
        p=SG.polygon([[-.2,-.2,1],[.2,-.2,1],[.2,.2,1],[-.2,.2,1]],chart=ch)
        empty=p.overlay(p,'difference');cancel=Event();cancel.set()
        with self.assertRaises(CancelledError):empty.classify([[0,0,1]],cancel=cancel)



ROOT = Path(__file__).resolve().parents[1]
ANGULAR_TOLERANCE = json.loads((ROOT/'cases/w01_geometry.json').read_text())[
    'acceptance']['unit_sphere_absolute_rad']


def decimal_arc_distance(point, start, end):
    """Independent finite-minor-arc reference using 90-digit dot/cross products.

    Projection membership uses oriented tangent half-spaces, not the native
    kernel's along-angle test. Endpoint and projection candidates are measured
    with high-range dot/cross products before the final scalar trig conversion.
    """
    with localcontext() as ctx:
        ctx.prec = 90
        def dec(v):
            return [Decimal.from_float(float(x)) for x in v]
        def dot(a, b):
            return sum((x*y for x,y in zip(a,b)), Decimal(0))
        def cross(a, b):
            return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
                    a[0]*b[1]-a[1]*b[0]]
        def norm(a):
            return dot(a,a).sqrt()
        p,a,b = dec(point),dec(start),dec(end)
        best = min(math.atan2(float(norm(cross(p,v))),float(dot(p,v)))
                   for v in (a,b))
        n = cross(a,b)
        if dot(n,n) and dot(p,cross(n,a)) >= 0 and dot(p,cross(b,n)) >= 0:
            sine = abs(dot(p,n))/(norm(p)*norm(n))
            best = min(best,math.asin(float(min(Decimal(1),sine))))
        return best


class AdditionalGeometryRegressions(unittest.TestCase):
    def test_short_arc_orientations_lengths_offsets_and_reversal(self):
        from atlas_tectonics._geometry_native import arc_distances
        rng=np.random.default_rng(27491)
        for trial in range(16):
            centre=rng.normal(size=3);centre/=np.linalg.norm(centre)
            tangent=np.cross(centre,np.eye(3)[int(np.argmin(abs(centre)))])
            tangent/=np.linalg.norm(tangent)
            normal=np.cross(centre,tangent)
            chart=SphericalChart(SphericalFrame(1.,'adversarial'),tuple(centre))
            for half_arc in (1e-2,1e-4,1e-6,1e-8,1e-10,1e-12):
                vertices=np.array([math.cos(half_arc)*centre-math.sin(half_arc)*tangent,
                                   math.cos(half_arc)*centre+math.sin(half_arc)*tangent])
                feature=SG.polyline(vertices,chart=chart)
                a=np.frombuffer(feature._segments_start,dtype=np.float64).reshape(-1,3)
                b=np.frombuffer(feature._segments_end,dtype=np.float64).reshape(-1,3)
                points=np.array([math.cos(offset)*centre+math.sin(offset)*normal
                                 for offset in (0.,1e-14,1e-10,1e-8)])
                expected=[decimal_arc_distance(p,a[0],b[0]) for p in points]
                with self.subTest(trial=trial,half_arc=half_arc):
                    np.testing.assert_allclose(feature.distance_to(points),expected,
                                               atol=ANGULAR_TOLERANCE,rtol=0.)
                    np.testing.assert_allclose(arc_distances(points,b,a),expected,
                                               atol=ANGULAR_TOLERANCE,rtol=0.)

    def test_finite_endpoints_not_infinite_great_circle(self):
        feature,centre=small_trace()
        tangent=np.array([1.,-1.,0.]);tangent/=np.linalg.norm(tangent)
        a=np.frombuffer(feature._segments_start,dtype=np.float64).reshape(-1,3)[0]
        b=np.frombuffer(feature._segments_end,dtype=np.float64).reshape(-1,3)[0]
        points=np.array([math.cos(offset)*centre+math.sin(offset)*tangent
                         for offset in (-4e-8,-1e-8,0.,1e-8,4e-8,math.pi)])
        expected=[decimal_arc_distance(p,a,b) for p in points]
        np.testing.assert_allclose(feature.distance_to(points),expected,
                                   atol=ANGULAR_TOLERANCE,rtol=0.)
        self.assertGreater(float(feature.distance_to(points[0])),2.9e-8)
        self.assertGreater(float(feature.distance_to(points[-1])),3.)

    def test_short_arc_near_miss_is_not_widened_into_corridor(self):
        feature,centre=small_trace()
        tangent=np.array([1.,-1.,0.]);tangent/=np.linalg.norm(tangent)
        normal=np.cross(centre,tangent)
        p=math.cos(1e-10)*centre+math.sin(1e-10)*normal
        self.assertFalse(bool(feature.within_distance(p,ANGULAR_TOLERANCE)))
        self.assertEqual(int(feature.classify(p,angular_tolerance_rad=ANGULAR_TOLERANCE)),-1)
        with GeometryIndex((GeometryFeature('trace',feature),)) as index:
            self.assertEqual(index.query(p,angular_tolerance_rad=ANGULAR_TOLERANCE).pairs.shape,(0,2))

    def test_zero_length_arc_from_point_contact_stays_point(self):
        from atlas_tectonics._geometry_native import arc_distances
        p=np.array([[1.,0.,0.],[0.,1.,0.],[-1.,0.,0.]])
        a=np.array([[1.,0.,0.]])
        np.testing.assert_allclose(arc_distances(p,a,a),[0.,math.pi/2,math.pi],
                                   atol=ANGULAR_TOLERANCE,rtol=0.)

    def test_short_arc_restore_and_index_preserve_queries(self):
        import pickle
        from atlas_tectonics.geometry_index import save_geometry, load_geometry
        from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
        import tempfile
        feature,point=small_trace()
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'geometry.db',StoreLimits(1024,1<<20,4<<20),Compression(codec='raw')) as store:
                key=save_geometry(feature,store)
                restored=load_geometry(store,key)
                self.assertEqual(feature.geometry_id,restored.geometry_id)
                for f in (restored,pickle.loads(pickle.dumps(feature))):
                    self.assertLessEqual(float(f.distance_to(point)),ANGULAR_TOLERANCE)
                    with GeometryIndex((GeometryFeature('trace',f),)) as index:
                        self.assertEqual(index.query(point,angular_tolerance_rad=ANGULAR_TOLERANCE).pairs.tolist(),[[0,0]])

    def test_zero_edge_refused_in_multipart_and_nested_imports(self):
        bad=shapely.LineString([[0,0],[1,0],[1,0],[2,0]])
        shapes=(bad,shapely.MultiLineString([bad]),
                shapely.GeometryCollection([shapely.Point(4,3),bad]),
                shapely.GeometryCollection([shapely.GeometryCollection([bad])]))
        for order in (0,1):
            for shape in shapes:
                with self.subTest(kind=shape.geom_type,byteorder=order):
                    with self.assertRaises(GeometryError):
                        PG.from_wkb(shapely.to_wkb(shape,byte_order=order),frame_id='p')

    def test_zero_edge_refused_in_spherical_projected_import(self):
        feature,_=small_trace()
        bad=shapely.LineString([[0,0],[.1,0],[.1,0],[.2,0]])
        with self.assertRaises(GeometryError):
            SG.from_projected_wkb(shapely.to_wkb(bad),chart=feature.chart)

    def test_imported_polygon_rings_share_zero_edge_rule(self):
        shell=[[0,0],[4,0],[4,4],[0,4],[0,0]]
        hole=[[1,1],[1,2],[1,2],[2,2],[2,1],[1,1]]
        bad=shapely.Polygon(shell,[hole])
        with self.assertRaises(GeometryError):PG.polygon(shell,holes=[hole],frame_id='p')
        with self.assertRaises(GeometryError):PG.from_wkb(shapely.to_wkb(bad),frame_id='p')

    def test_adjacent_components_and_closing_endpoint_remain_valid(self):
        # Equal vertices belonging to different parts do not form a zero edge.
        shape=shapely.MultiLineString([[(0,0),(1,0)],[(1,0),(2,0)]])
        imported=PG.from_wkb(shapely.to_wkb(shape),frame_id='p')
        self.assertEqual(imported.length_m,2.)
        ring=[[0,0],[1,0],[1,1],[0,1],[0,0]]
        direct=PG.polygon(ring,frame_id='p')
        loaded=PG.from_wkb(direct.wkb,frame_id='p')
        self.assertEqual(direct.geometry_id,loaded.geometry_id)
        self.assertEqual(loaded.area_m2,1.)

    def test_representable_extreme_radius_result_remains_finite(self):
        chart=SphericalChart(SphericalFrame(1e308,'extreme'),(1.,0.,0.))
        f=SG.polyline([[math.cos(.1),-math.sin(.1),0],
                       [math.cos(.1),math.sin(.1),0]],chart=chart)
        value=float(f.distance_to([math.cos(.2),math.sin(.2),0]))
        self.assertTrue(math.isfinite(value))
        self.assertLess(abs(value/1e308-.1),ANGULAR_TOLERANCE)
        with self.assertRaises(GeometryError):
            f.within_distance([-1.,0.,0.],1e308)

    def test_range_refusal_releases_budget_and_mutates_no_input(self):
        chart=SphericalChart(SphericalFrame(1e308,'extreme'),(1.,0.,0.))
        f=SG.polyline([[math.cos(.1),-math.sin(.1),0],
                       [math.cos(.1),math.sin(.1),0]],chart=chart)
        p=np.array([[-1.,0.,0.],[1.,0.,0.]])
        old=p.tobytes();budget=WorkBudget(1<<20)
        with self.assertRaises(GeometryError):f.distance_to(p,budget=budget)
        self.assertEqual(budget.reserved_bytes,0)
        self.assertEqual(p.tobytes(),old)

    def test_empty_query_honours_invalid_and_mid_query_cancellation(self):
        ch=SphericalChart(SphericalFrame(1.,'s'),(0.,0.,1.))
        p=SG.polygon([[-.2,-.2,1],[.2,-.2,1],[.2,.2,1],[-.2,.2,1]],chart=ch)
        empty=p.overlay(p,'difference')
        with self.assertRaises(GeometryError):empty.classify([[0,0,1]],cancel=object())
        class CancelOnSecondCheck:
            def __init__(self):self.calls=0
            def is_set(self):
                self.calls+=1
                return self.calls>=2
        budget=WorkBudget(1<<20)
        with self.assertRaises(CancelledError):
            empty.classify([[0,0,1]],cancel=CancelOnSecondCheck(),budget=budget)
        self.assertEqual(budget.reserved_bytes,0)
        np.testing.assert_array_equal(empty.classify([[0,0,1],[0,0,-1]]),[-1,-1])

    def test_native_flags_remain_strict_and_no_disk_cache(self):
        from atlas_tectonics._geometry_native import arc_distances
        self.assertFalse(arc_distances.targetoptions['fastmath'])
        self.assertTrue(arc_distances.targetoptions['nogil'])
        self.assertNotIn('parallel',arc_distances.targetoptions)
        self.assertEqual(type(arc_distances._cache).__name__,'NullCache')
