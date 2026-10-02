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


def collection_members(shape,kind):
    """Independent flattening for the checks below; not the package helper."""
    if shape.is_empty:return []
    if shape.geom_type==kind:return [shape]
    return [x for part in getattr(shape,'geoms',()) for x in collection_members(part,kind)]


class CollectionRuleRegressions(unittest.TestCase):
    """R7, 1 October 2026: a GeometryCollection may count no area or length twice.

    GEOS validates a collection member by member, so every refused shape here is
    valid for shapely. Before the rule each was admitted and summed its common
    area or length twice (review s03-2 and the trace cases found while scoping).
    Refusal is asserted, not its text: from_wkb reports only 'invalid stored
    geometry' and keeps the reason as __cause__.
    """
    A=shapely.Polygon([(0,0),(2,0),(2,2),(0,2)]);B=shapely.Polygon([(1,1),(3,1),(3,3),(1,3)])
    E=shapely.Polygon([(2,0),(4,0),(4,2),(2,2)]);T=shapely.Polygon([(2,2),(4,2),(4,4),(2,4)])
    FAR=shapely.Polygon([(9,9),(10,9),(10,10),(9,10)])
    INNER=shapely.Polygon([(.5,.5),(1.5,.5),(1.5,1.5),(.5,1.5)])
    HOLED=shapely.Polygon([(0,0),(10,0),(10,10),(0,10)],[[(3,3),(3,7),(7,7),(7,3)]])
    INHOLE=shapely.Polygon([(4,4),(6,4),(6,6),(4,6)])

    @staticmethod
    def raw(shape,order=1):return bytes(shapely.to_wkb(shape,byte_order=order))

    def refused_on_restore(self,shapes):
        for name,shape in shapes.items():
            self.assertTrue(shapely.is_valid(shape),name)
            for order in (0,1):
                with self.subTest(case=name,byteorder=order):
                    with self.assertRaises(GeometryError):PG.from_wkb(self.raw(shape,order),frame_id='p')

    def test_collection_polygons_are_held_to_the_multipolygon_rule(self):
        GC=shapely.GeometryCollection;A,B=self.A,self.B
        self.refused_on_restore({
            'overlap':GC([A,B]),
            'repeated member':GC([A,A]),
            'polygon inside another':GC([A,self.INNER]),
            'reversed-ring duplicate':GC([A,shapely.Polygon(list(A.exterior.coords)[::-1])]),
            'nested collections':GC([GC([A]),GC([B])]),
            'multipolygon member':GC([shapely.MultiPolygon([A,self.FAR]),B]),
            # Accepted consequence: the summed area was right, the shared edge
            # was counted twice in the perimeter, and a MultiPolygon refuses it.
            'shared edge':GC([A,self.E]),
            'overlap beside an unrelated trace':GC([A,shapely.LineString([(5,0),(6,0)]),B])})

    def test_collection_traces_are_held_to_the_multilinestring_rule_and_off_polygons(self):
        GC=shapely.GeometryCollection;line=shapely.LineString;A=self.A
        self.refused_on_restore({
            'overlapping traces':GC([line([(0,0),(2,0)]),line([(1,0),(3,0)])]),
            'repeated trace':GC([line([(0,0),(2,0)]),line([(0,0),(2,0)])]),
            'reversed repeated trace':GC([line([(0,0),(2,0)]),line([(2,0),(0,0)])]),
            'crossing traces':GC([line([(0,0),(2,2)]),line([(0,2),(2,0)])]),
            'trace ending on another trace':GC([line([(0,0),(2,0)]),line([(1,0),(1,1)])]),
            'nested overlapping traces':GC([GC([line([(0,0),(2,0)])]),
                                            shapely.MultiLineString([[(1,0),(3,0)],[(5,5),(6,6)]])]),
            'trace inside a polygon':GC([A,line([(.5,1),(1.5,1)])]),
            'trace along a polygon edge':GC([A,line([(0,0),(2,0)])]),
            'trace along part of an edge':GC([A,line([(.5,0),(1.5,0)])]),
            'trace crossing a polygon':GC([A,line([(-1,1),(3,1)])]),
            'trace entering a polygon':GC([A,line([(1,1),(3,1)])]),
            'trace along a hole edge':GC([self.HOLED,line([(3,4),(3,6)])]),
            'trace inside a nested polygon':GC([GC([shapely.MultiPolygon([A,self.FAR])]),
                                                GC([line([(.5,1),(1.5,1)])])])})

    def test_collection_and_multipart_members_are_admitted_or_refused_alike(self):
        GC=shapely.GeometryCollection;A=self.A
        refused=[(shapely.MultiPolygon,[A,self.B]),(shapely.MultiPolygon,[A,A]),
                 (shapely.MultiPolygon,[A,self.E]),(shapely.MultiPolygon,[A,self.INNER]),
                 (shapely.MultiLineString,[shapely.LineString([(0,0),(2,0)]),shapely.LineString([(1,0),(3,0)])]),
                 (shapely.MultiLineString,[shapely.LineString([(0,0),(2,2)]),shapely.LineString([(0,2),(2,0)])]),
                 (shapely.MultiLineString,[shapely.LineString([(0,0),(2,0)]),shapely.LineString([(1,0),(1,1)])])]
        for multi,members in refused:
            for shape in (multi(members),GC(members)):
                with self.subTest(kind=shape.geom_type,members=[m.wkt for m in members]):
                    with self.assertRaises(GeometryError):PG.from_wkb(self.raw(shape),frame_id='p')
        admitted=[(shapely.MultiPolygon,[A,self.T]),(shapely.MultiPolygon,[self.HOLED,self.INHOLE]),
                  (shapely.MultiLineString,[shapely.LineString([(0,0),(1,0)]),shapely.LineString([(1,0),(2,0)])]),
                  (shapely.MultiLineString,[shapely.LineString([(0,0),(1,0)]),shapely.LineString([(1,0),(2,0)]),
                                            shapely.LineString([(1,0),(1,1)])])]
        for multi,members in admitted:
            one=PG.from_wkb(self.raw(multi(members)),frame_id='p')
            many=PG.from_wkb(self.raw(GC(members)),frame_id='p')
            with self.subTest(members=[m.wkt for m in members]):
                self.assertEqual((many.area_m2,many.length_m),(one.area_m2,one.length_m))

    def test_admitted_collections_keep_kind_measures_and_bytes(self):
        GC=shapely.GeometryCollection;line=shapely.LineString;A,T=self.A,self.T
        cases={
            'point-touching members':(GC([A,T]),8.,16.),
            'polygon in another member\'s hole':(GC([self.HOLED,self.INHOLE]),88.,64.),
            'empty polygon member':(GC([A,shapely.Polygon()]),4.,8.),
            'empty nested collection':(GC([A,GC()]),4.,8.),
            'polygon and point':(GC([A,shapely.Point(5,5)]),4.,8.),
            'polygon and interior point':(GC([A,shapely.Point(1,1)]),4.,8.),
            'polygon and multipoint':(GC([A,shapely.MultiPoint([(5,5),(6,6)])]),4.,8.),
            'one multipolygon member':(GC([shapely.MultiPolygon([A,T])]),8.,16.),
            'single member':(GC([A]),4.,8.),
            'polygon and disjoint trace':(GC([A,line([(5,0),(6,0)])]),4.,9.),
            'trace ending on a polygon edge':(GC([A,line([(2,1),(3,1)])]),4.,9.),
            'trace ending at a polygon vertex':(GC([A,line([(2,2),(3,2)])]),4.,9.),
            'trace touching only a polygon corner':(GC([A,line([(-1,6),(5,-2)])]),4.,18.),
            'trace inside a hole':(GC([self.HOLED,line([(4,5),(6,5)])]),84.,58.),
            'traces joined end to end':(GC([line([(0,0),(1,0)]),line([(1,0),(2,0)])]),0.,2.),
            'nested mixed members':(GC([GC([A]),shapely.MultiLineString([[(5,0),(6,0)],[(6,0),(6,1)]]),
                                        shapely.Point(9,9)]),4.,10.)}
        for name,(shape,area,length) in cases.items():
            with self.subTest(case=name):
                little=PG.from_wkb(self.raw(shape),frame_id='p')
                self.assertEqual((little.kind,little.area_m2,little.length_m),('GeometryCollection',area,length))
                # Admission never rewrites the definition: same bytes, same identity.
                self.assertEqual(little.wkb,self.raw(shape))
                self.assertEqual(PG.from_wkb(self.raw(shape,0),frame_id='p').geometry_id,little.geometry_id)

    def test_point_contact_must_be_exact_in_the_stored_coordinates(self):
        from fractions import Fraction
        GC=shapely.GeometryCollection;line=shapely.LineString
        triangle=shapely.Polygon([(0,0),(1,0),(0,1)])
        # No tolerance. The trace is written to start on the edge x+y=1, but the
        # stored doubles 0.3 and 0.7 sum to less than one: it starts inside the
        # triangle and shares a rounding-size length with it. A test built on a
        # constructed intersection would round that length away and admit this.
        # Being exact is necessary, not always sufficient: the predicates are
        # GEOS's robust ones, not exact arithmetic (see the collinear-contact
        # test below).
        self.assertLess(Fraction(.3)+Fraction(.7),1)
        with self.assertRaises(GeometryError):
            PG.from_wkb(self.raw(GC([triangle,line([(.3,.7),(1.,1.5)])])),frame_id='p')
        # The same picture in binary fractions is an exact point contact.
        exact=PG.from_wkb(self.raw(GC([triangle,line([(.25,.75),(1.,1.5)])])),frame_id='p')
        self.assertEqual((exact.kind,exact.area_m2),('GeometryCollection',.5))

    def test_trace_and_polygon_comparison_is_bounded_by_the_overlay_pair_limit(self):
        GC=shapely.GeometryCollection;line=shapely.LineString;n=20
        # Only trace/polygon pairs whose bounding boxes meet are compared. Their
        # count is an execution envelope like an overlay's, not a tolerance.
        raw=self.raw(GC([self.A,line([(2,2),(3,2)]),line([(5,0),(6,0)]),line([(2,1),(3,1)])]))
        self.assertEqual(PG.from_wkb(raw,frame_id='p',limits=GeometryLimits(max_overlay_pairs=2)).length_m,11.)
        with self.assertRaises(GeometryError):
            PG.from_wkb(raw,frame_id='p',limits=GeometryLimits(max_overlay_pairs=1))
        # 400 squares, each with one trace leaving a corner: 400 neighbouring
        # pairs are compared, not the 160,000 of an all-against-all relation.
        squares=[shapely.Polygon([(3*i,3*j),(3*i+1,3*j),(3*i+1,3*j+1),(3*i,3*j+1)]) for i in range(n) for j in range(n)]
        traces=[line([(3*i+1,3*j+1),(3*i+2,3*j+1)]) for i in range(n) for j in range(n)]
        raw=self.raw(GC(squares+traces))
        many=PG.from_wkb(raw,frame_id='p',limits=GeometryLimits(max_overlay_pairs=n*n))
        self.assertEqual((many.area_m2,many.length_m),(float(n*n),float(5*n*n)))
        with self.assertRaises(GeometryError):
            PG.from_wkb(raw,frame_id='p',limits=GeometryLimits(max_overlay_pairs=n*n-1))
        self.assertEqual(PG.from_wkb(raw,frame_id='p').geometry_id,many.geometry_id)

    def test_batched_trace_and_polygon_comparison_matches_one_batch(self):
        GC=shapely.GeometryCollection;line=shapely.LineString;A,T=self.A,self.T
        # Two traces leave the corner shared by A and T, so each trace has two
        # neighbouring polygons. Small batches split both the candidate queries
        # and the relations of one query; the verdict may not depend on that.
        clean=[line([(2,2),(5,-2)]),line([(2,2),(-2,5)])]
        inside=line([(2.5,3),(3.5,3)])
        for batch in (1,2,3,GeometryLimits().batch_points):
            limits=GeometryLimits(batch_points=batch)
            with self.subTest(batch_points=batch):
                kept=PG.from_wkb(self.raw(GC([A,T,*clean])),frame_id='p',limits=limits)
                self.assertEqual((kept.area_m2,kept.length_m),(8.,26.))
                for traces in ([inside,*clean],[clean[0],inside,clean[1]],[*clean,inside]):
                    with self.assertRaises(GeometryError):
                        PG.from_wkb(self.raw(GC([A,T,*traces])),frame_id='p',limits=limits)

    def test_real_overlay_collections_still_round_trip(self):
        import pickle
        ell=PG.polygon([(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)],frame_id='p')
        other=PG.polygon([(1,1),(3,1),(3,2),(2,2),(2,3),(0,3),(0,2),(1,2)],frame_id='p')
        square=PG.polygon([(0,0),(2,0),(2,2),(0,2)],frame_id='p')
        crossing=PG.polyline([(-1,.25),(3,1.75)],frame_id='p')
        outputs={'area with two edge contacts':ell.overlay(other),
                 'polygon with the outside pieces of a crossing trace':square.overlay(crossing,'union')}
        for name,out in outputs.items():
            with self.subTest(case=name):
                self.assertEqual(out.kind,'GeometryCollection')
                self.assertEqual(sorted(x.geom_type for x in out._geom.geoms),['LineString','LineString','Polygon'])
                back=PG.from_wkb(out.wkb,frame_id='p')
                self.assertEqual((back.geometry_id,back.area_m2,back.length_m),(out.geometry_id,out.area_m2,out.length_m))
                self.assertEqual(pickle.loads(pickle.dumps(out)).geometry_id,out.geometry_id)

    def test_sampled_overlay_outputs_meet_the_collection_rule(self):
        # The rule must not refuse what a real overlay emits. Seeded half-unit
        # lattice shapes give results full of point and edge contacts. Each raw
        # GEOS result is checked here without the package, then must be admitted
        # unchanged. A sample, not a proof.
        rng=np.random.default_rng(20261001);collections=mixed=0
        def ring():
            n=int(rng.integers(3,8));t=np.sort(rng.uniform(0,2*math.pi,n));r=rng.uniform(.5,2.,n)
            return np.round((np.c_[r*np.cos(t),r*np.sin(t)]+rng.uniform(-1,1,2))*2)/2
        for trial in range(160):
            try:
                a=PG.polygon(ring(),frame_id='p')
                b=(PG.polyline(np.round(rng.uniform(-3,3,(int(rng.integers(2,5)),2))*2)/2,frame_id='p')
                   if trial%3 else PG.polygon(ring(),frame_id='p'))
            except GeometryError:continue
            for operation in ('intersection','union','difference','symmetric_difference'):
                raw=getattr(shapely,operation)(a._geom,b._geom,grid_size=0.)
                polygons=collection_members(raw,'Polygon');traces=collection_members(raw,'LineString')
                with self.subTest(trial=trial,operation=operation):
                    if len(polygons)>1:self.assertTrue(shapely.is_valid(shapely.multipolygons(polygons)))
                    if len(traces)>1:self.assertTrue(shapely.is_simple(shapely.multilinestrings(traces)))
                    for trace in traces:
                        for polygon in polygons:self.assertNotIn('1',shapely.relate(trace,polygon)[:2])
                    out=a.overlay(b,operation)
                    self.assertEqual(out.wkb,bytes(shapely.to_wkb(raw,byte_order=1,output_dimension=2)))
                    if out.kind=='GeometryCollection' and not out.is_empty:
                        collections+=1;mixed+=bool(polygons and traces)
                        self.assertEqual(PG.from_wkb(out.wkb,frame_id='p').geometry_id,out.geometry_id)
        self.assertGreater(collections,40);self.assertGreater(mixed,40)

    def test_private_and_spherical_routes_refuse_the_same_collections(self):
        GC=shapely.GeometryCollection;line=shapely.LineString
        chart=SphericalChart(SphericalFrame(1.,'u'),(0.,0.,1.))
        a=shapely.Polygon([(0,0),(.2,0),(.2,.2),(0,.2)]);b=shapely.Polygon([(.1,.1),(.3,.1),(.3,.3),(.1,.3)])
        shapes={'overlapping polygons':GC([a,b]),'repeated polygon':GC([a,a]),
                'overlapping traces':GC([line([(0,0),(.2,0)]),line([(.1,0),(.3,0)])]),
                'trace inside a polygon':GC([a,line([(.05,.1),(.15,.1)])])}
        for name,shape in shapes.items():
            with self.subTest(case=name):
                with self.assertRaises(GeometryError):PG._from_shape(shape,'p')
                with self.assertRaises(GeometryError):SG.from_projected_wkb(self.raw(shape),chart=chart)
                with self.assertRaises(GeometryError):SG._from_shape(shape,chart)
        # A point contact stays a spherical collection; each area is summed once.
        t=shapely.Polygon([(.2,.2),(.4,.2),(.4,.4),(.2,.4)])
        touching=SG.from_projected_wkb(self.raw(GC([a,t])),chart=chart)
        parts=[SG.from_projected_wkb(self.raw(x),chart=chart).area_steradians for x in (a,t)]
        self.assertEqual(touching.kind,'GeometryCollection')
        self.assertEqual(touching.area_steradians,math.fsum(parts))

    def test_self_certified_restore_routes_refuse_an_overlapping_collection(self):
        import hashlib,pickle,tempfile
        from atlas_tectonics.geometry import _restore_planar,_json,_SCHEMA
        from atlas_tectonics.spherical_geometry import _restore_spherical,_SCHEMA_SPHERE
        from atlas_tectonics.geometry_index import load_geometry
        from atlas_tectonics.storage import ArrayStore,StoreLimits,Compression
        GC=shapely.GeometryCollection
        # The stored identity is only a hash of frame and bytes, so a payload can
        # carry a correct identifier for a collection the rule refuses.
        raw=self.raw(GC([self.A,self.B]))
        ident=hashlib.sha256(_json({'schema':_SCHEMA,'space':'planar-metres','frame_id':'p'})+b'\0'+raw).hexdigest()
        meta={'schema':_SCHEMA,'space':'planar-metres','frame_id':'p','kind':'GeometryCollection','geometry_id':ident}
        chart=SphericalChart(SphericalFrame(1.,'u'),(0.,0.,1.))
        small=self.raw(GC([shapely.Polygon([(0,0),(.2,0),(.2,.2),(0,.2)]),
                           shapely.Polygon([(.1,.1),(.3,.1),(.3,.3),(.1,.3)])]))
        sphere_id=hashlib.sha256(_json({'schema':_SCHEMA_SPHERE,'chart':chart.descriptor()})+b'\0'+small).hexdigest()
        sphere_meta={'schema':_SCHEMA_SPHERE,'space':'sphere-minor-arcs','chart':chart.descriptor(),
                     'kind':'GeometryCollection','geometry_id':sphere_id}
        class Pickled:
            def __init__(self,restore,args):self.restore,self.args=restore,args
            def __reduce__(self):return (self.restore,self.args)
        for restore,args in ((_restore_planar,(raw,'p',ident)),(_restore_spherical,(small,chart,sphere_id))):
            with self.subTest(route=restore.__name__):
                with self.assertRaises(GeometryError):restore(*args)
                with self.assertRaises(GeometryError):pickle.loads(pickle.dumps(Pickled(restore,args)))
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'g.db',StoreLimits(1024,1<<20,4<<20),Compression(codec='raw')) as store:
                for key,payload,descriptor in ((ident,raw,meta),(sphere_id,small,sphere_meta)):
                    store.put(key,{'geometry_wkb':np.frombuffer(payload,dtype='u1')},descriptor)
                    with self.subTest(space=descriptor['space']):
                        with self.assertRaises(GeometryError):load_geometry(store,key)

    def test_repeated_member_collection_never_reaches_an_overlay_or_an_index(self):
        from unittest import mock
        # GC[A, A] used to be admitted with area 8 and then overlaid as if its
        # area were 4: its own measure disagreed with every result derived from it.
        raw=self.raw(shapely.GeometryCollection([self.A,self.A]))
        far=PG.polygon([(10,10),(11,10),(11,11)],frame_id='p')
        for operation in ('intersection','union','difference','symmetric_difference'):
            with self.subTest(operation=operation):
                with mock.patch('shapely.'+operation,side_effect=AssertionError('overlay reached')):
                    with self.assertRaises(GeometryError):
                        PG.from_wkb(raw,frame_id='p').overlay(far,operation)
        with self.assertRaises(GeometryError):
            GeometryIndex((GeometryFeature('twice',PG.from_wkb(raw,frame_id='p')),))

    def test_rechart_refuses_instead_of_admitting_an_overlap(self):
        GC=shapely.GeometryCollection
        # A contact that is not a shared vertex restores, but rounding in another
        # chart can push it across the neighbouring edge. in_chart then refuses,
        # as it already did for the same members as a MultiPolygon; before the
        # rule it returned the overlap as an admitted collection. Shared vertices
        # map to equal coordinates, so the two shared-vertex shapes below, whose
        # edges leave the vertex at an open angle, keep recharting. A shared
        # vertex alone is no guarantee (see the overlay-output test below). The
        # home coordinates are binary fractions: each contact below is exact
        # before the rechart.
        sphere=SphericalFrame(1.,'u');home=SphericalChart(sphere,(0.,0.,1.))
        square=shapely.Polygon([(0,0),(.25,0),(.25,.25),(0,.25)])
        corner=shapely.Polygon([(.25,.125),(.375,.0625),(.375,.1875)])
        cases={'polygon corner on an edge':(GC([square,corner]),True),
               'trace end on an edge':(GC([square,shapely.LineString([(.25,.125),(.375,.15625)])]),True),
               'trace through a corner':(GC([square,shapely.LineString([(.125,.375),(.375,.125)])]),True),
               'polygons sharing a vertex':(GC([square,shapely.Polygon([(.25,.25),(.375,.25),(.375,.375)])]),False),
               'trace from a shared vertex':(GC([square,shapely.LineString([(.25,.25),(.375,.3125)])]),False)}
        multipolygon=SG.from_projected_wkb(self.raw(shapely.MultiPolygon([square,corner])),chart=home)
        def recharted(geometry,chart):
            try:return geometry.in_chart(chart)
            except GeometryError:return None
        for name,(shape,unnoded) in cases.items():
            source=SG.from_projected_wkb(self.raw(shape),chart=home)
            rng=np.random.default_rng(20261001);refused=0;charts=96
            for _ in range(charts):
                chart=SphericalChart(sphere,tuple(np.array([0.,0.,1.])+rng.normal(scale=.05,size=3)))
                out=recharted(source,chart)
                with self.subTest(case=name):
                    if name=='polygon corner on an edge':
                        self.assertEqual(out is None,recharted(multipolygon,chart) is None)
                    if out is None:refused+=1;continue
                    polygons=collection_members(out._projected._geom,'Polygon')
                    traces=collection_members(out._projected._geom,'LineString')
                    if len(polygons)>1:self.assertTrue(shapely.is_valid(shapely.multipolygons(polygons)))
                    if polygons and traces:
                        matrix=shapely.relate(shapely.multilinestrings(traces),shapely.multipolygons(polygons))
                        self.assertNotIn('1',matrix[:2])
            with self.subTest(case=name,refused=refused):
                # Both outcomes occur for an un-noded contact; neither is an overlap.
                if unnoded:self.assertTrue(0<refused<charts)
                else:self.assertEqual(refused,0)

    def test_rechart_of_an_overlay_output_refuses_a_rounding_size_overlap(self):
        # Found by the independent check of the R7 rule. A shared vertex does
        # not protect a real overlay output. Each case unites a lattice rectangle
        # with a lattice trace after the trace alone had been moved to another
        # chart, so coordinates meant to coincide differ in their last bits. The
        # exact overlay then keeps a trace that starts two rounding steps along
        # the rectangle's edge from its corner (first case, a shared vertex) or
        # ends a rounding step short of an edge (second case). One more chart
        # rounds that trace into the rectangle. Each pair below is the overlay
        # output and its image in the target chart, recorded on Windows/CPython
        # 3.12.14 as WKB, so the two verdicts do not depend on how a platform
        # rounds the chart map. Rational arithmetic confirmed both images as
        # real overlaps.
        recorded={
            'trace leaving a node two rounding steps from a corner':(
                '01070000000200000001030000000100000006000000000000000000b03f000000000000b0bf000000000000b03f'
                '000000000000b03f000000000000d43f000000000000b03f000000000000d43f000000000000b0bf020000000000b03f'
                '000000000000b0bf000000000000b03f000000000000b0bf010200000003000000020000000000b03f000000000000b0bf'
                '010000000000d0bf010000000000b0bf010000000000c0bfffffffffffffc73f',
                '0107000000020000000103000000010000000600000099ffecda598fbe3faf68432c4111a7bf8a9ac16ac9a0be3f'
                '56cd61d02ca4b43fdcb66b4b8613d83fd2f948dd98dfb43f3c47bc199f05d83f6319bd249187a7bf9bffecda598fbe3f'
                'af68432c4111a7bf99ffecda598fbe3faf68432c4111a7bf0102000000030000009bffecda598fbe3faf68432c4111a7bf'
                '7bd260863164c8bf820f8ac4ff81a6bfd443bfaed474b1bf39ad7f416439ca3f'),
            'trace ending a rounding step short of an edge':(
                '01070000000200000001030000000100000005000000000000000000d0bf0000000000000000000000000000c0bf'
                '0000000000000000000000000000c0bf000000000000d0bf000000000000d0bf000000000000d0bf000000000000d0bf'
                '0000000000000000010200000002000000040000000000c03f020000000000c83f020000000000c8bf3fb75e298686323c',
                '0107000000020000000103000000010000000500000042e05bbdd7bbb3bfc4b421319a10d43fad405aa6b396b3bf'
                '78cd8a60b7abc73fb1b961b6a673d5bf9a8e7e2d8dfcc73f823c8e5e1f9dd5bf1a63b7b0a662d43f42e05bbdd7bbb3bf'
                'c4b421319a10d43f0102000000020000001057b6584b08bc3f36e81d5b459eb0bf752f8c2734a9b3bfa1b9bc02b0decf3f')}
        def shares_length(shape):
            polygons=collection_members(shape,'Polygon')
            return any('1' in shapely.relate(trace,polygon)[:2]
                       for trace in collection_members(shape,'LineString') for polygon in polygons)
        for name,(output,image) in recorded.items():
            with self.subTest(case=name):
                self.assertFalse(shares_length(shapely.from_wkb(bytes.fromhex(output))))
                self.assertTrue(shares_length(shapely.from_wkb(bytes.fromhex(image))))
                kept=PG.from_wkb(bytes.fromhex(output),frame_id='p')
                self.assertEqual((kept.kind,kept.wkb),('GeometryCollection',bytes.fromhex(output)))
                with self.assertRaises(GeometryError):PG.from_wkb(bytes.fromhex(image),frame_id='p')
        # The same two operations replayed on the running platform. Whatever its
        # rounding gives, in_chart refuses or returns members sharing no length.
        sphere=SphericalFrame(1.,'u');home=SphericalChart(sphere,(0.,0.,1.))
        def chart(*centre):return SphericalChart(sphere,tuple(float.fromhex(x) for x in centre))
        replayed={
            'trace leaving a node two rounding steps from a corner':(
                shapely.Polygon([(.0625,-.0625),(.3125,-.0625),(.3125,.0625),(.0625,.0625)]),
                shapely.LineString([(.0625,-.0625),(-.25,-.0625),(-.125,.1875)]),
                chart('0x1.30b09ed601c13p-6','0x1.1d16a57f37106p-4','0x1.feab6909fad0fp-1'),
                chart('-0x1.22407a139f467p-6','0x1.ce94b61de052dp-5','0x1.ff1a43cd35dbep-1')),
            'trace ending a rounding step short of an edge':(
                shapely.Polygon([(-.25,-.25),(-.125,-.25),(-.125,0.),(-.25,0.)]),
                shapely.LineString([(.125,.1875),(-.1875,0.)]),
                chart('-0x1.838a96196c779p-6','0x1.1835f8abc22bep-4','0x1.fea82bad306d9p-1'),
                chart('0x1.353154d6cbe7ep-4','-0x1.dc205e843ad35p-5','0x1.fdabd2ae07952p-1'))}
        for name,(area,trace,trace_chart,target) in replayed.items():
            try:
                moved_trace=SG.from_projected_wkb(self.raw(trace),chart=home).in_chart(trace_chart)
                out=SG.from_projected_wkb(self.raw(area),chart=home).overlay(moved_trace,'union')
            except GeometryError:continue
            rng=np.random.default_rng(20261001)
            targets=[target]+[SphericalChart(sphere,tuple(np.array([0.,0.,1.])+rng.normal(scale=.08,size=3)))
                              for _ in range(32)]
            for index,to in enumerate(targets):
                with self.subTest(case=name,chart=index):
                    try:moved=out.in_chart(to)
                    except GeometryError:continue
                    self.assertFalse(shares_length(moved._projected._geom))

    def test_exactly_collinear_contact_is_judged_as_the_multipart_form_judges_it(self):
        from fractions import Fraction
        GC=shapely.GeometryCollection
        # Found by the independent check of the R7 rule. The rule adds no
        # tolerance, but GEOS's predicates are robust floating-point tests, not
        # exact arithmetic. Here a corner of B, which is also the start of the
        # trace, lies exactly on an edge of A, a quarter of the way along it, and
        # B and the trace lie strictly outside A: a true point contact between
        # full-precision coordinates. GEOS 3.13.1 on the tested runtime calls it
        # a self-intersection and refuses the pair as a MultiPolygon, before and
        # after the collection rule. The outcome is GEOS's and is not asserted.
        # What is asserted is that the collection is judged exactly as the
        # multipart form and the relation judge it, with nothing added.
        A=shapely.from_wkb(bytes.fromhex(
            '01030000000100000004000000BA7C9C5F31B3E3BF68E4D0C2CA92CC3FDC4855EA46A6E83FE8371EB34B29E9BF'
            '7CA908CEB6EDE73F7C0F4AF2E881D43FBA7C9C5F31B3E3BF68E4D0C2CA92CC3F'))
        B=shapely.from_wkb(bytes.fromhex(
            '01030000000100000004000000A916409AA639D1BFD0640C089DD99DBF9BE8C3166E1CFBBF9EB6ECD6A2CBF1BF'
            '76275D34C79CEBBF1E72455BA27CFBBFA916409AA639D1BFD0640C089DD99DBF'))
        trace=shapely.from_wkb(bytes.fromhex(
            '010200000002000000A916409AA639D1BFD0640C089DD99DBF2B3E79D86875F4BF5E14199922A4F6BF'))
        def side(p,q,r):
            p,q,r=([Fraction(x) for x in point] for point in (p,q,r))
            return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
        p,q=A.exterior.coords[:2];v,*others=B.exterior.coords[:3]
        self.assertEqual(trace.coords[0],v)
        self.assertEqual(side(p,q,v),0)
        self.assertTrue(min(p[0],q[0])<v[0]<max(p[0],q[0]))
        self.assertTrue(all(side(p,q,w)<0 for w in (*others,trace.coords[1])))
        def admitted(shape):
            try:PG.from_wkb(self.raw(shape),frame_id='p');return True
            except GeometryError:return False
        pair=shapely.MultiPolygon([A,B])
        self.assertEqual(admitted(GC([A,B])),bool(shapely.is_valid(pair)))
        self.assertEqual(admitted(GC([A,B])),admitted(pair))
        self.assertEqual(admitted(GC([A,trace])),'1' not in shapely.relate(trace,A)[:2])

    def test_closed_trace_may_not_be_touched_by_another_trace(self):
        GC=shapely.GeometryCollection;line=shapely.LineString
        # Found by the independent check of the R7 rule. Two traces may meet
        # only at a point where both of them end. A closed trace has no end, so
        # no other trace may touch it, not even where it closes. That is the
        # MultiLineString rule; no length is counted twice in these shapes.
        ring=line([(0,0),(2,0),(1,1),(0,0)])
        touching={'trace leaving the closing point':[ring,line([(0,0),(-1,-1)])],
                  'trace leaving a middle vertex':[ring,line([(2,0),(3,0)])],
                  'two closed traces sharing their closing point':[ring,line([(0,0),(-2,0),(-1,-1),(0,0)])]}
        for name,members in touching.items():
            for shape in (shapely.MultiLineString(members),GC(members)):
                with self.subTest(case=name,kind=shape.geom_type):
                    with self.assertRaises(GeometryError):PG.from_wkb(self.raw(shape),frame_id='p')
        alone=PG.from_wkb(self.raw(GC([ring])),frame_id='p')
        self.assertEqual((alone.kind,alone.area_m2,alone.length_m),('GeometryCollection',0.,ring.length))
        apart=[ring,line([(5,0),(6,0)]),line([(5,5),(6,5),(6,6),(5,5)])]
        one=PG.from_wkb(self.raw(shapely.MultiLineString(apart)),frame_id='p')
        many=PG.from_wkb(self.raw(GC(apart)),frame_id='p')
        self.assertEqual((many.area_m2,many.length_m),(one.area_m2,one.length_m))
