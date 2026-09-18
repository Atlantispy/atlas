"""W01 stage 2 geometry: independent measures, topology and engineering contracts.

Analytic rectangles/triangles, scalar winding and independently known spherical
areas/distances check more than round trips. GEOS-vs-GEOS comparisons are explicitly
only index/execution checks, not independent verification of the geometry engine.
No timing thresholds, relaxed earlier tolerances, world simulation or installation.
"""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
import shapely
from shapely.geometry import Polygon, GeometryCollection, Point, LineString

from atlas_tectonics import (GeometryError, TectonicsError, GeometryLimits,
    PlanarGeometry as PG, SphericalGeometry as SG, SphericalChart, SphericalFrame,
    GeometryFeature as Feature, GeometryIndex, audit_coverage, save_geometry,
    load_geometry, Rotation, geometry_runtime)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics._geometry_native import arc_distances

ROOT=Path(__file__).resolve().parents[1]
CASE=json.loads((ROOT/'cases/w01_geometry.json').read_text())['acceptance']
ATOL=CASE['unit_sphere_absolute_rad'];RTOL=CASE['relative_tolerance']
S=SphericalFrame(CASE['reference_radius_m'],'sphere-test-axes')
CH=SphericalChart(S,(1.,1.,1.))
NORTH=SphericalChart(S,(0.,0.,1.))


def box(x0=0,y0=0,x1=2,y1=2,frame='p'):
    return PG.polygon([[x0,y0],[x1,y0],[x1,y1],[x0,y1]],frame_id=frame)


def unit(lon,lat):
    lon,lat=math.radians(lon),math.radians(lat)
    return [math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat)]


def sphere_box(a=.5,b=.5,chart=NORTH):
    xy=np.array([[-a,-b],[a,-b],[a,b],[-a,b]])
    return SG.polygon(chart._unproject(xy),chart=chart)


def independent_ray_inside(vertices,p):
    # Scalar ray crossing, used away from boundaries so no ambiguous side choice.
    inside=False;x,y=p
    for a,b in zip(vertices,np.roll(vertices,-1,axis=0)):
        if (a[1]>y)!=(b[1]>y):
            cross=a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if x<cross:inside=not inside
    return inside


class PlanarGeometryTests(unittest.TestCase):
    def test_rectangle_area_and_perimeter(self):
        p=box(0,0,3,4);self.assertEqual(p.area_m2,12);self.assertEqual(p.length_m,14)

    def test_rational_triangle_area(self):
        a=np.array([[0.,0.],[.25,0.],[0.,.5]])
        expected=float(Fraction(1,4)*Fraction(1,2)/2)
        self.assertEqual(PG.polygon(a,frame_id='p').area_m2,expected)

    def test_concave_polygon(self):
        a=np.array([[0,0],[3,0],[3,1],[1,1],[1,3],[0,3.]])
        p=PG.polygon(a,frame_id='p');self.assertEqual(p.area_m2,5)
        assert_array_equal(p.classify([[.5,2],[2,2],[1,1]]),[1,-1,0])

    def test_concave_scalar_membership_reference(self):
        a=np.array([[0,0],[3,0],[3,1],[1,1],[1,3],[0,3.]])
        q=np.random.default_rng(302).uniform(-1,4,(900,2));p=PG.polygon(a,frame_id='p')
        expected=np.array([1 if independent_ray_inside(a,x) else -1 for x in q])
        assert_array_equal(p.classify(q),expected)

    def test_holes_area_membership(self):
        p=PG.polygon([[0,0],[4,0],[4,4],[0,4]],holes=([[1,1],[2,1],[2,2],[1,2]],),frame_id='p')
        self.assertEqual(p.area_m2,15)
        assert_array_equal(p.classify([[.5,.5],[1.5,1.5],[1,1],[4,4]]),[1,-1,0,0])

    def test_reversed_ring_same_measures(self):
        a=np.array([[0,0],[2,0],[2,3],[0,3.]])
        p=PG.polygon(a,frame_id='p');q=PG.polygon(a[::-1],frame_id='p')
        self.assertEqual(p.area_m2,q.area_m2);self.assertEqual(p.length_m,q.length_m)
        self.assertNotEqual(p.geometry_id,q.geometry_id)

    def test_open_closed_ring_equivalent_bytes(self):
        a=np.array([[0,0],[2,0],[2,3],[0,3.]])
        self.assertEqual(PG.polygon(a,frame_id='p').geometry_id,PG.polygon(np.vstack((a,a[0])),frame_id='p').geometry_id)

    def test_boundary_band_does_not_snap_geometry(self):
        p=box();before=p.wkb
        assert_array_equal(p.classify([[2+1e-8,1]],boundary_tolerance_m=1e-7),[0])
        assert_array_equal(p.classify([[2+1e-8,1]]),[-1]);self.assertEqual(before,p.wkb)

    def test_distance_inside_and_to_perimeter(self):
        p=box();assert_allclose(p.distance_to([[1,1],[3,3]]),[0,math.sqrt(2)])
        assert_allclose(p.distance_to([[1,1],[3,3]],boundary=True),[1,math.sqrt(2)])

    def test_finite_trace_distance_and_corridor(self):
        p=PG.polyline([[0,0],[2,0]],frame_id='p')
        assert_allclose(p.distance_to([[1,3],[4,3]]),[3,math.sqrt(13)])
        assert_array_equal(p.within_distance([[1,3],[4,3]],3),[True,False])
        assert_array_equal(p.classify([[1,0],[0,0],[0,1]]),[0,0,-1])

    def test_polyline_direction_retained(self):
        p=PG.polyline([[0,0],[1,0],[1,1]],frame_id='p')
        q=PG.polyline([[1,1],[1,0],[0,0]],frame_id='p')
        self.assertEqual(p.length_m,q.length_m);self.assertNotEqual(p.geometry_id,q.geometry_id)

    def test_overlapping_rectangle_intersection(self):
        p=box().overlay(box(1,1,3,3));self.assertEqual(p.area_m2,1);self.assertEqual(p.length_m,4)

    def test_union_and_difference(self):
        a,b=box(),box(1,1,3,3)
        self.assertEqual(a.overlay(b,'union').area_m2,7)
        self.assertEqual(a.overlay(b,'difference').area_m2,3)
        self.assertEqual(a.overlay(b,'symmetric_difference').area_m2,6)

    def test_touching_edge_retained(self):
        g=box().overlay(box(2,0,4,2));self.assertEqual(g.kind,'LineString');self.assertEqual(g.length_m,2)

    def test_touching_vertex_retained(self):
        g=box().overlay(box(2,2,4,4));self.assertEqual(g.kind,'Point');self.assertEqual(g.area_m2,0)
        assert_array_equal(g.classify([[2,2],[2,3]]),[0,-1])

    def test_empty_intersection(self):
        g=box().overlay(box(3,3,4,4));self.assertTrue(g.is_empty)
        assert_array_equal(g.classify([[0,0]]),[-1])
        with self.assertRaises(GeometryError):g.distance_to([[0,0]])

    def test_multipart_difference(self):
        g=box(0,0,4,4).overlay(box(1,-1,3,5),'difference')
        self.assertEqual(g.kind,'MultiPolygon');self.assertEqual(g.area_m2,8)
        assert_array_equal(g.classify([[.5,2],[2,2],[3.5,2]]),[1,-1,1])

    def test_collection_keeps_region_and_trace_semantics(self):
        p=PG._from_shape(GeometryCollection([Polygon([(0,0),(1,0),(1,1),(0,1)]),LineString([(2,0),(3,0)])]),'p')
        assert_array_equal(p.classify([[.5,.5],[2.5,0],[2.5,.1]]),[1,0,-1])
        assert_allclose(p.distance_to([[.5,.5]],boundary=True),[.5])

    def test_self_crossing_region_refused(self):
        with self.assertRaises(GeometryError):PG.polygon([[0,0],[2,2],[0,2],[2,0]],frame_id='p')

    def test_collinear_region_refused(self):
        with self.assertRaises(GeometryError):PG.polygon([[0,0],[1,1],[2,2]],frame_id='p')

    def test_repeated_vertices_refused(self):
        for a in ([[0,0],[2,0],[2,0],[0,2]],[[0,0],[2,0],[1,1],[2,0],[0,2]]):
            with self.assertRaises(GeometryError):PG.polygon(a,frame_id='p')

    def test_invalid_holes_refused(self):
        shell=[[0,0],[4,0],[4,4],[0,4]]
        for holes in (([[5,5],[6,5],[6,6],[5,6]],),([[0,0],[1,0],[1,1],[0,1]],),
                      ([[1,1],[3,1],[3,3],[1,3]],[[1.5,1.5],[2,1.5],[2,2],[1.5,2]])):
            with self.assertRaises(GeometryError):PG.polygon(shell,holes=holes,frame_id='p')

    def test_trace_self_crossing_refused(self):
        with self.assertRaises(GeometryError):PG.polyline([[0,0],[2,2],[0,2],[2,0]],frame_id='p')

    def test_invalid_query_inputs(self):
        for q in ([],[1,2,3],[True,1],np.ma.array([[1.,2.]]),[[np.inf,0]],[[1+1j,0]]):
            with self.assertRaises((GeometryError,TectonicsError)):box().classify(q)

    def test_frame_mismatch_refused(self):
        with self.assertRaises(GeometryError):box(frame='a').overlay(box(frame='b'))

    def test_queries_are_immutable(self):
        for a in (box().classify([[1,1]]),box().distance_to([[3,3]]),box().within_distance([[3,3]],2)):
            with self.assertRaises(ValueError):a.setflags(write=True)

    def test_capture_detaches_and_restore_preserves(self):
        a=np.array([[0.,0.],[2,0],[2,2],[0,2]]);p=PG.polygon(a,frame_id='p');a[:]=99
        self.assertEqual(p.area_m2,4)
        for q in (copy.deepcopy(p),pickle.loads(pickle.dumps(p)),PG.from_wkb(p.wkb,frame_id='p')):
            self.assertEqual(q.geometry_id,p.geometry_id);self.assertEqual(q.area_m2,4)
        with self.assertRaises(FrozenInstanceError):p.frame_id='q'

    def test_strided_and_batched_queries(self):
        q=np.arange(40.).reshape(10,4)[:,::2];p=box()
        assert_array_equal(p.classify(q,limits=GeometryLimits(batch_points=1)),p.classify(q))

    def test_limits_before_native_allocation(self):
        with mock.patch('atlas_tectonics.geometry.Polygon',side_effect=AssertionError('allocated')):
            with self.assertRaises(GeometryError):PG.polygon(np.zeros((5,2)),frame_id='p',limits=GeometryLimits(max_vertices=4))
        a,b=box(),box(1,1,3,3)
        with mock.patch('shapely.intersection',side_effect=AssertionError('overlay')):
            with self.assertRaises(GeometryError):a.overlay(b,limits=GeometryLimits(max_overlay_pairs=1))

    def test_identical_geometry_reuses_verified_definition(self):
        p=box()
        with mock.patch('shapely.intersection',side_effect=AssertionError('unnecessary overlay')):
            self.assertIs(p.overlay(p,limits=GeometryLimits(max_overlay_pairs=1)),p)
        self.assertTrue(p.overlay(p,'difference').is_empty)

    def test_disjoint_bbox_avoids_quadratic_admission(self):
        p=box();q=box(5,5,6,6)
        self.assertTrue(p.overlay(q,limits=GeometryLimits(max_overlay_pairs=1)).is_empty)

    def test_many_holes_keep_exact_area(self):
        holes=[]
        for i in range(10):
            for j in range(10):
                x,y=1+3*i,1+3*j
                holes.append([[x,y],[x+1,y],[x+1,y+1],[x,y+1]])
        p=PG.polygon([[0,0],[32,0],[32,32],[0,32]],holes=holes,frame_id='p')
        self.assertEqual(p.area_m2,1024-100)

    def test_small_memory_budget_refuses_and_releases(self):
        b=WorkBudget(100)
        with self.assertRaises(MemoryLimitError):box().classify(np.ones((100,2)),budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_cancel_refuses_without_mutating(self):
        e=threading.Event();e.set();p=box();ident=p.geometry_id
        with self.assertRaises(CancelledError):p.classify([[1,1]],cancel=e)
        with self.assertRaises(CancelledError):p.overlay(box(),cancel=e)
        self.assertEqual(p.geometry_id,ident)


class SphericalGeometryTests(unittest.TestCase):
    def test_octant_independent_area_perimeter(self):
        p=SG.polygon(np.eye(3),chart=CH)
        self.assertAlmostEqual(p.area_m2,math.pi/2*S.radius_m**2,places=12)
        self.assertAlmostEqual(p.length_m,3*math.pi/2*S.radius_m,places=12)

    def test_rectangle_solid_angle_independent(self):
        for a,b in ((.1,.3),(.8,.4),(2.,3.)):
            p=sphere_box(a,b)
            expected=4*math.atan(a*b/math.sqrt(1+a*a+b*b))
            self.assertAlmostEqual(p.area_steradians,expected,places=12)

    def test_tiny_patch_area(self):
        a=1e-8;p=sphere_box(a,a)
        expected=4*math.atan(a*a/math.sqrt(1+2*a*a))
        assert_allclose(p.area_steradians,expected,rtol=CASE['small_spherical_area_relative'],atol=0)

    def test_hole_area(self):
        outer=NORTH._unproject(np.array([[-1,-1],[1,-1],[1,1],[-1,1.]]))
        hole=NORTH._unproject(np.array([[-.2,-.2],[.2,-.2],[.2,.2],[-.2,.2]]))
        p=SG.polygon(outer,holes=(hole,),chart=NORTH)
        self.assertAlmostEqual(p.area_m2,sphere_box(1,1).area_m2-sphere_box(.2,.2).area_m2,places=12)
        assert_array_equal(p.classify([[0,0,1],NORTH._unproject(np.array([[.5,0]]))[0]]),[-1,1])

    def test_concave_area_is_signed_not_convex_hull(self):
        xy=np.array([[0,0],[2,0],[2,1],[1,1],[1,2],[0,2.]])
        p=SG.polygon(NORTH._unproject(xy),chart=NORTH)
        quad=lambda x0,y0,x1,y1: SG.polygon(NORTH._unproject(np.array([[x0,y0],[x1,y0],[x1,y1],[x0,y1]])),chart=NORTH)
        expected=quad(0,0,2,1).area_m2+quad(0,1,1,2).area_m2
        self.assertAlmostEqual(p.area_m2,expected,places=12)
        assert_array_equal(p.classify(NORTH._unproject(np.array([[.5,1.5],[1.5,1.5]]))),[1,-1])

    def test_pole_interior(self):
        assert_array_equal(sphere_box().classify([[0,0,1],[0,0,-1]]),[1,-1])

    def test_dateline_crossing_not_world_spanning(self):
        ch=SphericalChart(S,(-1,0,0))
        p=SG.polygon([unit(170,-10),unit(-170,-10),unit(-170,10),unit(170,10)],chart=ch)
        assert_array_equal(p.classify([unit(180,0),unit(-180,0),unit(0,0)]),[1,1,-1])
        self.assertLess(p.area_steradians,.2)

    def test_vertices_and_arc_midpoints_classified_boundary(self):
        p=SG.polygon(np.eye(3),chart=CH)
        assert_array_equal(p.classify([[1,0,0],[1,1,0],[0,1,1],[1,0,1]]),[0,0,0,0])

    def test_numerical_boundary_band_is_not_owned(self):
        p=SG.polygon(np.eye(3),chart=CH)
        q=np.array([[1,1,-1e-15]])
        assert_array_equal(p.classify(q),[0])
        self.assertLessEqual(p.classify(q,angular_tolerance_rad=0)[0],0)

    def test_finite_equatorial_arc_distances(self):
        ch=SphericalChart(S,(1,0,0));p=SG.polyline([unit(-45,0),unit(45,0)],chart=ch)
        q=[unit(0,30),unit(90,0),unit(180,0),unit(0,90)]
        assert_allclose(p.distance_to(q),S.radius_m*np.array([math.pi/6,math.pi/4,3*math.pi/4,math.pi/2]),rtol=RTOL,atol=ATOL)

    def test_spherical_corridor_not_planar_buffer(self):
        ch=SphericalChart(S,(1,0,0));p=SG.polyline([unit(-45,0),unit(45,0)],chart=ch)
        assert_array_equal(p.within_distance([unit(0,5),unit(0,20)],S.radius_m*math.radians(10)),[True,False])

    def test_inside_distance_zero_boundary_positive(self):
        p=SG.polygon(np.eye(3),chart=CH)
        self.assertEqual(p.distance_to([[1,1,1]])[0],0)
        self.assertAlmostEqual(p.distance_to([[1,1,1]],boundary=True)[0],S.radius_m*math.asin(1/math.sqrt(3)),places=12)

    def test_geodesic_not_projected_area(self):
        p=sphere_box(1,1)
        self.assertGreater(abs(p.area_m2-p._projected.area_m2*S.radius_m**2),1)

    def test_rotation_invariant_measures(self):
        p=SG.polygon(np.eye(3),chart=CH);rot=Rotation.from_axis_angle([1,2,3],.7)
        q=SG.polygon(rot.apply(np.eye(3)),chart=SphericalChart(S,tuple(rot.apply(CH.centre))))
        self.assertAlmostEqual(p.area_m2,q.area_m2,places=12)
        self.assertAlmostEqual(p.length_m,q.length_m,places=12)
        assert_array_equal(q.classify(rot.apply([[1,1,1],[1,0,0],[-1,-1,-1]])),[1,0,-1])

    def test_rechart_preserves_geometry_metrics(self):
        p=sphere_box(.2,.3);q=p.in_chart(SphericalChart(S,(.05,.02,1)))
        self.assertAlmostEqual(p.area_m2,q.area_m2,places=12)
        assert_array_equal(p.classify([[0,0,1],[1,0,0]]),q.classify([[0,0,1],[1,0,0]]))

    def test_spherical_overlay_area_partition(self):
        a=sphere_box(.8,.8);b=sphere_box(.2,.3)
        inter=a.overlay(b);difference=a.overlay(b,'difference')
        self.assertAlmostEqual(inter.area_m2,b.area_m2,places=12)
        self.assertAlmostEqual(difference.area_m2+inter.area_m2,a.area_m2,places=12)

    def test_spherical_overlay_with_other_chart(self):
        a=sphere_box(.8,.8);b=sphere_box(.2,.3).in_chart(SphericalChart(S,(.1,0,1)))
        self.assertAlmostEqual(a.overlay(b).area_m2,b.area_m2,places=12)

    def test_crossing_arc_intersection_retains_point(self):
        ch=SphericalChart(S,(1,0,0))
        a=SG.polyline([unit(-30,0),unit(30,0)],chart=ch)
        b=SG.polyline([unit(0,-30),unit(0,30)],chart=ch)
        p=a.overlay(b);self.assertEqual(p.kind,'Point')
        assert_allclose(p.distance_to([[1,0,0]]),[0],atol=ATOL)

    def test_shared_arc_retained(self):
        a=SG.polygon([[1,0,0],[0,1,0],[0,0,1]],chart=CH)
        b=SG.polygon([[1,0,0],[0,0,1],[0,-1,0]],chart=SphericalChart(S,(1,-1,1)))
        # A common chart just off the y=0 plane accommodates both parts here only
        # after replacing 90-degree lateral extremes with supported local points.
        ch=SphericalChart(S,(1,0,0))
        a=SG.polygon([unit(0,-20),unit(20,0),unit(0,20)],chart=ch)
        b=SG.polygon([unit(0,-20),unit(0,20),unit(-20,0)],chart=ch)
        inter=a.overlay(b);self.assertEqual(inter.kind,'LineString')
        self.assertAlmostEqual(inter.length_m,S.radius_m*math.radians(40),places=12)

    def test_antipodal_and_horizon_refused(self):
        ch=SphericalChart(S,(1,0,0))
        for vertices in (([1,0,0],[-1,0,0],[0,1,0]),([1,0,0],[0,1,0],[0,0,1])):
            with self.assertRaises(GeometryError):SG.polygon(vertices,chart=ch)

    def test_invalid_spherical_rings_refused(self):
        for xy in ([[0,0],[1,1],[0,1],[1,0]],[[0,0],[1,0],[2,0]]):
            with self.assertRaises(GeometryError):SG.polygon(NORTH._unproject(np.array(xy,float)),chart=NORTH)

    def test_opposite_features_no_false_overlap_claim(self):
        a=sphere_box(.1,.1)
        south=SphericalChart(S,(0,0,-1));b=sphere_box(.1,.1,south)
        with self.assertRaises(GeometryError):a.overlay(b)

    def test_sphere_radius_and_frame_mismatch(self):
        a=sphere_box()
        for sphere in (SphericalFrame(3,S.frame_id),SphericalFrame(S.radius_m,'other')):
            b=sphere_box(chart=SphericalChart(sphere,(0,0,1)))
            with self.assertRaises(GeometryError):a.overlay(b)

    def test_bad_directions_masks_and_empty(self):
        p=sphere_box()
        for q in ([[0,0,0]],[[np.nan,0,1]],np.ma.array([[0,0,1]]),[] ,[[True,0,1]]):
            with self.assertRaises((GeometryError,TectonicsError)):p.classify(q)

    def test_batched_and_strided_match(self):
        rng=np.random.default_rng(59);q=rng.normal(size=(600,6))[:,::2];p=sphere_box()
        assert_array_equal(p.classify(q),p.classify(q,limits=GeometryLimits(batch_points=7)))
        assert_allclose(p.distance_to(q),p.distance_to(q,limits=GeometryLimits(batch_points=7)),atol=0,rtol=0)

    def test_direction_scale_invariance(self):
        p=sphere_box();q=np.array([[.1,.2,1.]])
        assert_array_equal(p.classify(q),p.classify(q*1e250))
        assert_allclose(p.distance_to(q*1e-250,boundary=True),p.distance_to(q,boundary=True),atol=ATOL)

    def test_restore_exact_identity(self):
        rng=np.random.default_rng(170)
        for _ in range(12):
            ch=SphericalChart(S,tuple(rng.normal(size=3)))
            p=sphere_box(.2,.3,ch)
            for q in (copy.deepcopy(p),pickle.loads(pickle.dumps(p))):
                self.assertEqual(p.geometry_id,q.geometry_id);self.assertEqual(p.area_m2,q.area_m2)
            self.assertEqual(ch.descriptor(),SphericalChart.from_descriptor(ch.descriptor()).descriptor())

    def test_spherical_memory_admission_and_cancellation(self):
        p=sphere_box();b=WorkBudget(100)
        with self.assertRaises(MemoryLimitError):p.classify([[0,0,1]],budget=b)
        self.assertEqual(b.reserved_bytes,0)
        e=threading.Event();e.set()
        with self.assertRaises(CancelledError):p.distance_to([[0,0,1]],cancel=e)

    def test_compiler_settings_preserved(self):
        sphere_box().distance_to([[1,0,0]])
        self.assertTrue(arc_distances.nopython_signatures)
        self.assertFalse(arc_distances.targetoptions['fastmath'])
        self.assertTrue(arc_distances.targetoptions['nogil'])
        self.assertNotIn('parallel',arc_distances.targetoptions)


class IndexCoverageStorageTests(unittest.TestCase):
    def test_index_matches_exhaustive_and_stable_order(self):
        fs=[Feature('b',box(1,0,3,2)),Feature('a',box(0,0,2,2))]
        pts=np.array([[.5,1],[1,1],[3,1],[4,1],[1,0]])
        with GeometryIndex(fs) as index:
            actual=index.query(pts);expected=[]
            for i,p in enumerate(pts):
                for j,f in enumerate(sorted(fs,key=lambda f:f.feature_id)):
                    if f.geometry.classify(p)>=0:expected.append((i,j))
            assert_array_equal(actual.pairs,expected);self.assertEqual(actual.feature_ids,('a','b'))
            with self.assertRaises(ValueError):actual.pairs.setflags(write=True)

    def test_index_keeps_all_boundary_candidates(self):
        with GeometryIndex([Feature('a',box(0,0,1,1)),Feature('b',box(1,0,2,1))]) as index:
            assert_array_equal(index.query([[1,.5]]).pairs,[[0,0],[0,1]])

    def test_index_prunes_many_spatial_features(self):
        fs=[Feature(f'f{i:03d}',box(i*3,0,i*3+1,1)) for i in range(100)]
        pts=np.array([[i*3+.5,.5] for i in range(100)])
        with GeometryIndex(fs) as index:
            hits=index.query(pts)
            self.assertEqual(len(hits.pairs),100)
            self.assertEqual(hits.candidate_pairs,100);self.assertEqual(hits.exhaustive_pairs,10000)

    def test_index_multipart_deduplicates_hits(self):
        g=box(0,0,1,1).overlay(box(3,0,4,1),'union')
        with GeometryIndex([Feature('m',g)]) as index:
            assert_array_equal(index.query([[.5,.5],[3.5,.5],[2,.5]]).pairs,[[0,0],[1,0]])

    def test_spherical_index_multiple_charts_matches_exhaustive(self):
        charts=[SphericalChart(S,(0,0,1)),SphericalChart(S,(1,0,0)),SphericalChart(S,(-1,0,0))]
        fs=[Feature(str(i),sphere_box(.3,.4,ch)) for i,ch in enumerate(charts)]
        rng=np.random.default_rng(991);q=np.vstack((rng.normal(size=(300,3)),[[0,0,1],[1,0,0],[-1,0,0]]))
        expected=[]
        for j,f in enumerate(fs):
            for i in np.flatnonzero(f.geometry.classify(q)>=0):expected.append((i,j))
        with GeometryIndex(fs) as index:
            assert_array_equal(index.query(q).pairs,np.array(sorted(expected)))

    def test_spherical_index_boundary_band_no_false_negative(self):
        p=SG.polygon(np.eye(3),chart=CH);q=np.array([[1,1,-1e-15],[1,1,-1e-6]])
        with GeometryIndex([Feature('a',p)]) as index:
            assert_array_equal(index.query(q).pairs,[[0,0]])

    def test_index_same_inputs_after_thread_queries(self):
        fs=[Feature('a',box())];q=np.random.default_rng(77).uniform(-1,3,(100,2))
        with GeometryIndex(fs) as index:
            expected=index.query(q).pairs.tobytes()
            with ThreadPoolExecutor(3) as pool:
                for out in pool.map(lambda _:index.query(q),range(12)):
                    self.assertEqual(out.pairs.tobytes(),expected)

    def test_index_close_releases_retained_reservation(self):
        b=WorkBudget(1<<20);idx=GeometryIndex([Feature('a',box())],budget=b)
        self.assertGreater(b.reserved_bytes,0);idx.close();self.assertEqual(b.reserved_bytes,0)
        with self.assertRaises(GeometryError):idx.query([[1,1]])

    def test_index_public_inputs_immutable(self):
        with GeometryIndex([Feature('a',box())]) as idx:
            for name,value in [('features',()),('identity','fake'),('limits',GeometryLimits())]:
                with self.assertRaises(GeometryError):setattr(idx,name,value)

    def test_index_invalid_frames_duplicate_ids(self):
        cases=([Feature('a',box()),Feature('a',box())],
               [Feature('a',box()),Feature('b',box(frame='q'))],
               [Feature('a',box()),Feature('b',sphere_box())])
        for fs in cases:
            with self.assertRaises(GeometryError):GeometryIndex(fs)

    def test_index_max_hits_and_cancel(self):
        fs=[Feature('a',box()),Feature('b',box())]
        with GeometryIndex(fs,limits=GeometryLimits(max_hits=3)) as idx:
            with self.assertRaises(GeometryError):idx.query([[1,1],[1,1]])
            e=threading.Event();e.set()
            with self.assertRaises(CancelledError):idx.query([[1,1]],cancel=e)

    def test_index_lazy_batches(self):
        seen=[]
        def batches():
            for i in range(5):seen.append(i);yield [[1,1]]
        with GeometryIndex([Feature('a',box())]) as idx:
            it=idx.query_batches(batches());next(it);it.close()
            self.assertEqual(seen,[0])

    def test_coverage_complete_and_contact(self):
        report=audit_coverage(box(),[Feature('left',box(0,0,1,2)),Feature('right',box(1,0,2,2))])
        self.assertTrue(report.complete);self.assertEqual(len(report.contacts),1)
        self.assertEqual(report.contacts[0][2].length_m,2)

    def test_coverage_gap_not_repaired(self):
        fs=[Feature('a',box(0,0,.9,2)),Feature('b',box(1,0,2,2))]
        ids=tuple(f.geometry.geometry_id for f in fs);report=audit_coverage(box(),fs)
        self.assertFalse(report.complete);self.assertAlmostEqual(report.gap_area_m2,.2)
        self.assertEqual(tuple(f.geometry.geometry_id for f in fs),ids)

    def test_coverage_overlap_not_deleted(self):
        report=audit_coverage(box(),[Feature('a',box(0,0,1.1,2)),Feature('b',box(1,0,2,2))])
        self.assertFalse(report.complete);self.assertAlmostEqual(report.overlaps[0][2].area_m2,.2)

    def test_coverage_outside_not_clipped(self):
        report=audit_coverage(box(),[Feature('wide',box(-1,0,2,2))])
        self.assertFalse(report.complete);self.assertEqual(report.outside_area_m2,2)

    def test_coverage_hole_stays_a_gap(self):
        g=PG.polygon([[0,0],[4,0],[4,4],[0,4]],holes=([[1,1],[2,1],[2,2],[1,2]],),frame_id='p')
        report=audit_coverage(box(0,0,4,4),[Feature('holed',g)])
        self.assertEqual(report.gap_area_m2,1)

    def test_spherical_coverage_uses_spherical_areas(self):
        outer=sphere_box(.6,.6);inner=sphere_box(.2,.2)
        report=audit_coverage(outer,[Feature('centre',inner)])
        self.assertFalse(report.complete)
        self.assertAlmostEqual(report.gap_area_m2,outer.area_m2-inner.area_m2,places=12)

    def test_coverage_rejects_trace(self):
        with self.assertRaises(GeometryError):audit_coverage(box(),[Feature('f',PG.polyline([[0,0],[1,1]],frame_id='p'))])

    def test_store_round_trip_both_spaces_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'geo.db',StoreLimits(1024,1<<20,4<<20)) as store:
                for g in (box(),sphere_box(.2,.3,SphericalChart(S,(.13,.27,1)))):
                    key=save_geometry(g,store);count=store.statistics()['unique_chunks']
                    save_geometry(g,store);self.assertEqual(store.statistics()['unique_chunks'],count)
                    out=load_geometry(store,key)
                    self.assertEqual(out.geometry_id,g.geometry_id);self.assertEqual(out.area_m2,g.area_m2)

    def test_backup_cold_restore_without_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'g.db';backup=Path(tmp)/'copy.db';limits=StoreLimits(1024,1<<20,4<<20)
            g=sphere_box()
            with ArrayStore(p,limits) as s:save_geometry(g,s);s.backup_to(backup)
            p.unlink()
            with ArrayStore(backup,limits) as s:self.assertEqual(load_geometry(s,g.geometry_id).geometry_id,g.geometry_id)

    def test_fresh_process_geometry_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'g.db';g=sphere_box()
            with ArrayStore(p,StoreLimits(1024,1<<20,4<<20)) as s:save_geometry(g,s)
            code="""from atlas_tectonics import load_geometry
from atlas_tectonics.storage import ArrayStore,StoreLimits
import sys
with ArrayStore(sys.argv[1],StoreLimits(1024,1<<20,4<<20)) as s:
 print(load_geometry(s,sys.argv[2]).geometry_id)
"""
            env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1')
            proc=subprocess.run([sys.executable,'-B','-c',code,str(p),g.geometry_id],env=env,text=True,capture_output=True,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(proc.stdout.strip(),g.geometry_id)

    def test_corruption_refused_not_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'g.db',StoreLimits(1024,1<<20,4<<20)) as s:
                g=box();save_geometry(g,s)
                s._db.execute('UPDATE chunks SET payload=?',(b'corrupt',))
                with self.assertRaises(StoreError):load_geometry(s,g.geometry_id)

    def test_invalid_wkb_never_repaired(self):
        for raw in (b'',b'notwkb',shapely.to_wkb(Polygon([(0,0),(1,1),(0,1),(1,0)]))):
            with self.assertRaises(GeometryError):PG.from_wkb(raw,frame_id='p')

    def test_oversized_wkb_counts_refused_before_native_parser(self):
        import struct
        raw=b'\x01'+struct.pack('<II',2,1_000_000_000)
        with mock.patch('shapely.from_wkb',side_effect=AssertionError('native allocation attempted')):
            with self.assertRaises(GeometryError):PG.from_wkb(raw,frame_id='p')

    def test_wkb_trailing_bytes_and_z_refused(self):
        for raw in (box().wkb+b'extra',shapely.to_wkb(Point(1,2,3))):
            with self.assertRaises(GeometryError):PG.from_wkb(raw,frame_id='p')

    def test_big_endian_wkb_is_explicitly_decoded(self):
        raw=shapely.to_wkb(Polygon([(0,0),(2,0),(2,2),(0,2)]),byte_order=0)
        self.assertEqual(PG.from_wkb(raw,frame_id='p').geometry_id,box().geometry_id)

    def test_context_tracks_geometry_functions_and_native_runtime(self):
        import atlas_tectonics.geometry as geo
        with ExecutionContext() as ctx:
            self.assertIn('shapely',ctx._runtime['versions'])
            before=ctx.identity
            with mock.patch.object(geo,'geometry_runtime',lambda:{'changed':True}):
                with self.assertRaises(TectonicsError):ctx.verify()
            self.assertEqual(before,ctx.identity)

    def test_engine_report(self):
        record=geometry_runtime();self.assertEqual(record['shapely'],shapely.__version__)
        self.assertIn('minor',record['spherical_model'])


if __name__=='__main__':unittest.main()
