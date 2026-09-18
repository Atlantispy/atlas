"""Stage-3 independent fixtures plus storage, ownership and resource regressions.

Reference rectangles, holes, rational partitions and spherical orthonormal frames
check the new boundary graph. Native-vs-native tests are explicitly integration
checks, not independent accuracy proof. No performance pass threshold or new
physical tolerance is introduced; old test sources remain unchanged.
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
from shapely.geometry import Polygon, MultiPolygon, LineString

from atlas_tectonics import (PlanarGeometry as PG, SphericalGeometry as SG,
    SphericalChart, SphericalFrame, BoundaryRegion as Region, BoundaryNetwork,
    build_boundary_network as build, save_boundary_network, load_boundary_network,
    GeometryError, GeometryLimits, boundary_motion, Rotation, rigid_velocity)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
from atlas_tectonics.reuse import ExecutionContext

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = json.loads((ROOT/'cases/w01_boundaries.json').read_text())['acceptance']
ATOL = ACCEPT['planar_absolute_m']; RTOL = ACCEPT['relative_tolerance']
S = SphericalFrame(2., 'axes'); CH = SphericalChart(S, (0., 0., 1.))


def box(a=0., b=0., c=2., d=1., frame='plane'):
    return PG.polygon([(a,b),(c,b),(c,d),(a,d)], frame_id=frame)


def parts():
    return box(), (Region('left', 'plate-A', box(0,0,1,1)), Region('right', 'plate-B', box(1,0,2,1)))


def square_network(): return build(*parts())


def sphere_region(x0, y0, x1, y1, chart=CH):
    # An exact chart-coordinate definition is a declared geometry, not snapped
    # output. Tests of angular input construction are separate below.
    raw = box(x0,y0,x1,y1).wkb
    return SG.from_projected_wkb(raw, chart=chart)


def sphere_network(chart=CH, same_plate=False):
    dom=sphere_region(-.5,-.5,.5,.5,chart)
    return build(dom,(Region('left','A',sphere_region(-.5,-.5,0,.5,chart)),
                      Region('right','A' if same_plate else 'B',sphere_region(0,-.5,.5,.5,chart))))


def node_at(net, xy):
    ix=np.flatnonzero(np.all(net.vertex_xy==xy,axis=1))
    if len(ix)!=1: raise AssertionError('expected one node')
    return net.junction(int(ix[0]))


class SharedPlanarTests(unittest.TestCase):
    def test_rectangle_shared_once(self):
        n=square_network();self.assertEqual(n.edge_count,7);self.assertEqual(n.vertex_count,6)
        self.assertEqual(len(n.interplate_edges),1)
        self.assertEqual(n.adjacency(),(('plate-A','plate-B'),))

    def test_left_right_are_geometric(self):
        n=square_network();e=n.edge(n.interplate_edges[0])
        self.assertEqual(e.start,(1.,0.));self.assertEqual(e.end,(1.,1.))
        self.assertEqual((e.left_region_id,e.right_region_id),('left','right'))

    def test_reversal_swaps_regions_plates_and_direction(self):
        n=square_network();e=n.edge(n.interplate_edges[0]);r=e.reversed()
        self.assertEqual(r.start,e.end);self.assertEqual(r.left_plate_id,e.right_plate_id)
        self.assertEqual(r.boundary_id,e.boundary_id);self.assertEqual(r.reversed(),e)

    def test_reference_motion_is_used_consistently(self):
        n=square_network();i=n.interplate_edges[0];f=n.frames([i])
        ref=boundary_motion([1,2],[4,6],f.tangent[0],[.5,-.5])
        r=n.motion({'plate-A':[1,2],'plate-B':[4,6]},[.5,-.5])
        assert_allclose(r.values_m_s[0,:2],[ref.opening_m_s,ref.tangential_m_s],rtol=RTOL,atol=ATOL)

    def test_motion_reversal_keeps_opening_and_tangential(self):
        n=square_network();v={'plate-A':[1,2],'plate-B':[4,6]}
        a=n.motion(v,[2,3]);b=n.motion(v,[2,3],reverse=True)
        assert_array_equal(a.values_m_s[:,:2],b.values_m_s[:,:2])
        assert_array_equal(a.values_m_s[:,2],-b.values_m_s[:,3])

    def test_common_velocity_shift(self):
        n=square_network()
        a=n.motion({'plate-A':[1,2],'plate-B':[4,6]},[2,3])
        b=n.motion({'plate-A':[11,22],'plate-B':[14,26]},[12,23])
        assert_array_equal(a.values_m_s,b.values_m_s)

    def test_region_uses_are_opposite(self):
        n=square_network();i=n.interplate_edges[0]
        self.assertEqual(dict(n.uses('left'))[i],-dict(n.uses('right'))[i])
        self.assertEqual(sum(len(n.uses(r)) for r in n.region_ids),8)

    def test_perimeter_integrals_cancel_normals(self):
        n=square_network();f=n.frames()
        for region in n.region_ids:
            integral=np.zeros(2)
            for i,s in n.uses(region):integral+=s*f.length_m[i]*f.right_normal[i]
            assert_allclose(integral,[0,0],rtol=RTOL,atol=ATOL)

    def test_reversed_input_rings_same_connectivity(self):
        dom,rs=parts();other=[]
        for r in rs:
            other.append(Region(r.region_id,r.plate_id,PG.polygon(np.asarray(r.geometry._geom.exterior.coords)[::-1],frame_id='plane')))
        a=build(dom,rs);b=build(dom,tuple(other))
        assert_array_equal(a.edge_vertices,b.edge_vertices);assert_array_equal(a.side_regions,b.side_regions)
        self.assertNotEqual(a.network_id,b.network_id) # input provenance retained

    def test_input_order_does_not_change_identity(self):
        d,r=parts();self.assertEqual(build(d,r).network_id,build(d,r[::-1]).network_id)

    def test_extra_collinear_vertex_splits_shared_edge(self):
        left=PG.polygon([[0,0],[1,0],[1,.5],[1,1],[0,1]],frame_id='plane')
        n=build(box(),(Region('left','A',left),Region('right','B',box(1,0,2,1))))
        self.assertEqual(len(n.interplate_edges),2)
        self.assertEqual(math.fsum(n.frames(n.interplate_edges).length_m),1)
        for i in n.interplate_edges:self.assertEqual(n.edge(i).left_region_id,'left')

    def test_same_plate_seam_not_plate_adjacency(self):
        d,r=parts();r=(r[0],Region('right','plate-A',r[1].geometry));n=build(d,r)
        self.assertEqual(n.interplate_edges,());self.assertEqual(n.adjacency(),())
        self.assertEqual(n.adjacency(by_plate=False),(('left','right'),))
        self.assertEqual(sum(n.role(i)=='patch-seam' for i in range(n.edge_count)),1)

    def test_three_region_junction_has_three_sectors(self):
        r=(Region('a','A',box(0,0,1,2)),Region('b','B',box(1,0,2,1)),Region('c','C',box(1,1,2,2)))
        n=build(box(0,0,2,2),r);j=node_at(n,(1,1))
        self.assertEqual(j.degree,3);self.assertEqual(set(j.sector_region_ids),{'a','b','c'})
        self.assertEqual(j.contact_region_pairs,())
        self.assertEqual(n.adjacency(),(('A','B'),('A','C'),('B','C')))

    def test_four_region_point_contacts_not_edge_adjacency(self):
        r=(Region('a','A',box(0,0,1,1)),Region('b','B',box(1,0,2,1)),
           Region('c','C',box(0,1,1,2)),Region('d','D',box(1,1,2,2)))
        n=build(box(0,0,2,2),r);j=node_at(n,(1,1))
        self.assertEqual(j.degree,4);self.assertEqual(j.contact_region_pairs,(('a','d'),('b','c')))
        self.assertNotIn(('A','D'),n.adjacency());self.assertNotIn(('B','C'),n.adjacency())

    def test_hole_orientation_and_island_owner(self):
        ring=PG.polygon([[0,0],[4,0],[4,4],[0,4]],holes=([[1,1],[3,1],[3,3],[1,3]],),frame_id='plane')
        n=build(box(0,0,4,4),(Region('ring','R',ring),Region('island','I',box(1,1,3,3))))
        self.assertEqual(len(n.interplate_edges),4)
        self.assertEqual(math.fsum(n.frames(n.interplate_edges).length_m),8.)
        for i,s in n.uses('island'):
            e=n.edge(i,reverse=s<0);self.assertEqual(e.left_region_id,'island')

    def test_domain_hole_is_explicit_exterior(self):
        d=PG.polygon([[0,0],[4,0],[4,4],[0,4]],holes=([[1,1],[3,1],[3,3],[1,3]],),frame_id='plane')
        n=build(d,(Region('r','R',d),));self.assertEqual(n.edge_count,8)
        self.assertTrue(all(n.role(i)=='exterior' for i in range(8)))

    def test_concave_shared_boundary(self):
        a=PG.polygon([[0,0],[3,0],[3,1],[1,1],[1,3],[0,3]],frame_id='plane')
        n=build(box(0,0,3,3),(Region('a','A',a),Region('b','B',box(1,1,3,3))))
        self.assertEqual(math.fsum(n.frames(n.interplate_edges).length_m),4.)

    def test_multipart_point_touch_domain(self):
        a=box(0,0,1,1);b=box(1,1,2,2)
        d=PG._from_shape(MultiPolygon([a._geom,b._geom]),'plane')
        n=build(d,(Region('a','A',a),Region('b','B',b)))
        self.assertEqual(n.adjacency(),());self.assertEqual(node_at(n,(1,1)).contact_region_pairs,(('a','b'),))

    def test_fractional_rectangle_known_total_length(self):
        a,b,c,d=map(float,[Fraction(1,8),Fraction(1,4),Fraction(7,8),Fraction(3,4)])
        g=box(a,b,c,d);n=build(g,(Region('r','R',g),))
        self.assertEqual(math.fsum(n.frames().length_m),2*((c-a)+(d-b)))

    def test_shared_trace_correct_and_reversed(self):
        n=square_network();p=PG.polyline([[1,0],[1,1]],frame_id='plane')
        self.assertEqual(n.validate_trace(p,left_region_id='left',right_region_id='right'),((n.interplate_edges[0],1),))
        p=PG.polyline([[1,1],[1,0]],frame_id='plane')
        self.assertEqual(n.validate_trace(p,left_region_id='right',right_region_id='left'),((n.interplate_edges[0],-1),))

    def test_partial_trace_validated_not_moved(self):
        n=square_network();p=PG.polyline([[1,.25],[1,.75]],frame_id='plane');raw=p.wkb
        self.assertEqual(len(n.validate_trace(p,left_region_id='left',right_region_id='right')),1)
        self.assertEqual(raw,p.wkb)

    def test_trace_wrong_sides_rejected(self):
        n=square_network();p=PG.polyline([[1,0],[1,1]],frame_id='plane')
        with self.assertRaises(GeometryError):n.validate_trace(p,left_region_id='right',right_region_id='left')

    def test_near_trace_not_snapped(self):
        n=square_network();p=PG.polyline([[1+1e-10,.1],[1+1e-10,.9]],frame_id='plane')
        with self.assertRaises(GeometryError):n.validate_trace(p,left_region_id='left',right_region_id='right')

    def test_trace_outside_and_corner_contact_refused(self):
        n=square_network()
        for xy in ([[1,-1],[1,.5]],[[0,0],[-1,-1]]):
            p=PG.polyline(xy,frame_id='plane')
            with self.assertRaises(GeometryError):n.validate_trace(p,left_region_id='left',right_region_id='right')

    def test_exterior_trace_explicit_none(self):
        n=square_network();p=PG.polyline([[0,0],[1,0]],frame_id='plane')
        self.assertEqual(len(n.validate_trace(p,left_region_id='left',right_region_id=None)),1)

    def test_tiny_feature_sides_do_not_use_epsilon_probe(self):
        for width in (1e-12,1e-30):
            d=box(0,0,2*width,width)
            n=build(d,(Region('a','A',box(0,0,width,width)),Region('b','B',box(width,0,2*width,width))))
            self.assertEqual(len(n.interplate_edges),1)
            self.assertEqual(n.edge(n.interplate_edges[0]).left_region_id,'a')

    def test_frames_fraction_endpoints(self):
        n=square_network();i=n.interplate_edges[0]
        assert_array_equal(n.frames([i],fraction=0).position_m,[[1,0]])
        assert_array_equal(n.frames([i],fraction=1).position_m,[[1,1]])
        assert_allclose(n.frames([i]).right_normal,[[1,0]],atol=ATOL)


class BoundaryRejectionTests(unittest.TestCase):
    def test_gap_refused(self):
        with self.assertRaisesRegex(GeometryError,'gap'):
            build(box(),(Region('a','A',box(0,0,.9,1)),Region('b','B',box(1,0,2,1))))

    def test_tiny_gap_refused(self):
        with self.assertRaises(GeometryError):build(box(),(Region('a','A',box(0,0,1-1e-12,1)),Region('b','B',box(1,0,2,1))))

    def test_overlap_refused(self):
        with self.assertRaisesRegex(GeometryError,'overlap'):
            build(box(),(Region('a','A',box(0,0,1.1,1)),Region('b','B',box(1,0,2,1))))

    def test_tiny_overlap_refused(self):
        with self.assertRaises(GeometryError):build(box(),(Region('a','A',box(0,0,1+1e-12,1)),Region('b','B',box(1,0,2,1))))

    def test_outside_region_refused(self):
        with self.assertRaisesRegex(GeometryError,'outside'):build(box(),(Region('a','A',box(-1,0,2,1)),))

    def test_identical_regions_not_deduplicated_away(self):
        with self.assertRaises(GeometryError):build(box(),(Region('a','A',box()),Region('b','B',box())))

    def test_invalid_regions_frames_and_ids(self):
        d,r=parts()
        for values in ((),[r[0],r[0]],['a'],[Region('a','A',box(frame='other'))]):
            with self.assertRaises(GeometryError):build(d,values)
        with self.assertRaises(GeometryError):Region('a','A',PG.polyline([[0,0],[1,1]],frame_id='plane'))
        with self.assertRaises(GeometryError):BoundaryNetwork()

    def test_vertex_limit_before_noding(self):
        with mock.patch('shapely.node',side_effect=AssertionError('native allocation')):
            with self.assertRaises(GeometryError):build(*parts(),limits=GeometryLimits(max_vertices=4))

    def test_pair_limit(self):
        with self.assertRaises(GeometryError):build(*parts(),limits=GeometryLimits(max_overlay_pairs=1))

    def test_memory_refusal_and_release(self):
        b=WorkBudget(16)
        with mock.patch('shapely.node',side_effect=AssertionError('native allocation')):
            with self.assertRaises(MemoryLimitError):build(*parts(),budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_already_cancelled_before_work(self):
        e=threading.Event();e.set()
        with mock.patch('shapely.node',side_effect=AssertionError('work attempted')):
            with self.assertRaises(CancelledError):build(*parts(),cancel=e)

    def test_cancel_during_build_releases_budget(self):
        class Cancel:
            def __init__(self):self.n=0
            def is_set(self):self.n+=1;return self.n>10
        b=WorkBudget(4<<20)
        with self.assertRaises(CancelledError):build(*parts(),budget=b,cancel=Cancel())
        self.assertEqual(b.reserved_bytes,0)

    def test_wrong_index_types(self):
        n=square_network()
        for x in ([-1],[100],[True],[1.5],np.ma.array([1]),np.array([2**64-1],dtype='u8')):
            with self.assertRaises(GeometryError):n.frames(x)

    def test_wrong_motion_owner_and_exterior(self):
        n=square_network()
        with self.assertRaises(GeometryError):n.motion({'plate-A':[0,0]},[0,0])
        with self.assertRaises(GeometryError):n.motion({'plate-A':[0,0],'plate-B':[0,0]},[0,0],indices=[0])

    def test_bad_motion_arrays_and_overflow(self):
        n=square_network()
        for v in ([1,2,3],np.ma.array([1,2]),[np.inf,0]):
            with self.assertRaises(ValueError):n.motion({'plate-A':v,'plate-B':[0,0]},[0,0])
        with self.assertRaises(GeometryError):n.motion({'plate-A':[-1e308,0],'plate-B':[1e308,0]},[0,0])

    def test_bad_fraction_or_reverse(self):
        n=square_network()
        for x in (-1,2,np.nan,True):
            with self.assertRaises(ValueError):n.frames(fraction=x)
        with self.assertRaises(GeometryError):n.frames(reverse='yes')

    def test_empty_selection_valid_and_cancelled(self):
        n=square_network();self.assertEqual(n.frames([]).position_m.shape,(0,2))
        event=threading.Event();event.set()
        with self.assertRaises(CancelledError):n.frames([],cancel=event)


class SharedSphericalTests(unittest.TestCase):
    def test_north_pole_network(self):
        n=sphere_network();self.assertEqual(n.edge_count,7);self.assertEqual(n.adjacency(),(('A','B'),))
        f=n.frames(n.interplate_edges)
        assert_allclose(np.linalg.norm(f.position_m,axis=1),2,rtol=RTOL,atol=ATOL)
        assert_allclose(np.sum(f.position_m*f.tangent,axis=1),0,atol=ATOL)
        assert_allclose(np.sum(f.tangent*f.right_normal,axis=1),0,atol=ATOL)

    def test_known_arc_length(self):
        n=sphere_network();f=n.frames(n.interplate_edges)
        self.assertAlmostEqual(f.length_m[0],2*2*math.atan(.5),places=12)

    def test_seam_chart_not_lon_rectangle(self):
        chart=SphericalChart(S,(-1.,0.,0.));n=sphere_network(chart)
        self.assertEqual(len(n.interplate_edges),1)
        assert_allclose(n.frames(n.interplate_edges).position_m,[[-2.,0.,0.]],atol=ATOL)

    def test_polar_tangents_match_independent_cross_product(self):
        n=sphere_network();e=n.edge(n.interplate_edges[0]);a=np.array(e.start);b=np.array(e.end)
        left=np.cross(a,b);left/=np.linalg.norm(left);mid=(a+b)/np.linalg.norm(a+b)
        expected=np.cross(left,mid);f=n.frames(n.interplate_edges)
        assert_allclose(f.tangent,[expected],atol=ATOL);assert_allclose(f.right_normal,[-left],atol=ATOL)

    def test_spherical_reversal(self):
        n=sphere_network();a=n.frames(n.interplate_edges);b=n.frames(n.interplate_edges,reverse=True)
        assert_allclose(a.position_m,b.position_m,atol=ATOL)
        assert_allclose(a.tangent,-b.tangent,atol=ATOL);assert_allclose(a.right_normal,-b.right_normal,atol=ATOL)
        assert_allclose(a.length_m,b.length_m,atol=ATOL)

    def test_spherical_fraction_follows_arc_not_chart(self):
        n=sphere_network();i=n.interplate_edges[0];e=n.edge(i)
        a=np.array(e.start);b=np.array(e.end);p=n.frames([i],fraction=.25).position_m[0]/2
        theta=lambda x,y:2*math.atan2(np.linalg.norm(x-y),np.linalg.norm(x+y))
        self.assertAlmostEqual(theta(a,p)/theta(a,b),.25,places=12)

    def test_same_plate_patch_seam(self):
        n=sphere_network(same_plate=True);self.assertEqual(n.adjacency(),())
        self.assertEqual(sum(n.role(i)=='patch-seam' for i in range(n.edge_count)),1)

    def test_radius_scales_lengths_not_sides(self):
        a=sphere_network();b=sphere_network(SphericalChart(SphericalFrame(20.,'axes'),(0,0,1)))
        assert_allclose(b.frames().length_m,10*a.frames().length_m,atol=ATOL)
        assert_array_equal(a.side_regions,b.side_regions)

    def test_sphere_frame_mismatch(self):
        d=sphere_region(-.5,-.5,.5,.5)
        wrong=SphericalChart(SphericalFrame(2,'wrong'),(0,0,1))
        with self.assertRaises(GeometryError):build(d,(Region('x','X',sphere_region(-.5,-.5,.5,.5,wrong)),))

    def test_no_common_chart_refuses(self):
        d=sphere_region(-.5,-.5,.5,.5)
        south=SphericalChart(S,(0,0,-1))
        with self.assertRaises(GeometryError):build(d,(Region('x','X',sphere_region(-.5,-.5,.5,.5,south)),))

    def test_spherical_trace_verified(self):
        n=sphere_network();p=SG.from_projected_wkb(PG.polyline([[0,-.5],[0,.5]],frame_id='p').wkb,chart=CH)
        result=n.validate_trace(p,left_region_id='left',right_region_id='right')
        self.assertEqual(result,((n.interplate_edges[0],1),))

    def test_short_arcs_stable_frames(self):
        chart=SphericalChart(S,(1.,2.,3.))
        for width in (1e-5,1e-7):
            n=build(sphere_region(-width,-width,width,width,chart),
                (Region('a','A',sphere_region(-width,-width,0,width,chart)),Region('b','B',sphere_region(0,-width,width,width,chart))))
            frames=n.frames(n.interplate_edges)
            assert_allclose(np.linalg.norm(frames.tangent,axis=1),1,atol=ATOL)
            assert_allclose(np.sum(frames.tangent*frames.right_normal,axis=1),0,atol=ATOL)

    def test_sphere_motion_rigid_velocity_and_radial_diagnostic(self):
        n=sphere_network();f=n.frames(n.interplate_edges);p=f.position_m
        a=rigid_velocity(p,[0,1,0]);b=rigid_velocity(p,[0,2,0])
        m=n.motion({'A':a,'B':b},np.zeros_like(p));rev=n.motion({'A':a,'B':b},np.zeros_like(p),reverse=True)
        assert_allclose(m.values_m_s[:,:2],rev.values_m_s[:,:2],atol=ATOL)
        assert_allclose(m.values_m_s[:,4],0,atol=ATOL)
        m=n.motion({'A':np.zeros_like(p),'B':p/2},np.zeros_like(p))
        assert_allclose(m.values_m_s[:,4],1,atol=ATOL)

    def test_actual_direction_constructor_supported(self):
        # At the north chart, using one set of shared unit vertices retains joins.
        xy=np.array([[-.5,-.5],[0,-.5],[.5,-.5],[.5,.5],[0,.5],[-.5,.5]])
        u=CH._unproject(xy)
        d=SG.polygon(u[[0,1,2,3,4,5]],chart=CH)
        a=SG.polygon(u[[0,1,4,5]],chart=CH);b=SG.polygon(u[[1,2,3,4]],chart=CH)
        n=build(d,(Region('a','A',a),Region('b','B',b)))
        self.assertEqual(len(n.interplate_edges),1)


class BoundaryEngineeringTests(unittest.TestCase):
    def test_native_index_candidates_bounded_by_sparse_geometry(self):
        d=box(0,0,20,1);regions=tuple(Region(str(i).zfill(3),str(i),box(i,0,i+1,1)) for i in range(20))
        n=build(d,regions)
        self.assertEqual(len(n.interplate_edges),19)
        self.assertLess(n.statistics['segment_candidate_pairs'],80**2//4)

    def test_immutability_and_private_descriptors(self):
        n=square_network()
        for a in (n.vertex_xy,n.edge_vertices,n.side_regions,n.frames().tangent):
            with self.assertRaises(ValueError):a.setflags(write=True)
        shape=n.edge_vertices.shape;a=n.edge_vertices;a.shape=(a.size,)
        self.assertEqual(n.edge_vertices.shape,shape)
        with self.assertRaises(FrozenInstanceError):n.network_id='x'
        self.assertIs(copy.deepcopy(n),n)

    def test_pickle_rebuilds_tree_and_identity(self):
        for n in (square_network(),sphere_network()):
            r=pickle.loads(pickle.dumps(n));self.assertEqual(r.network_id,n.network_id)
            assert_array_equal(r.side_regions,n.side_regions)
            with self.assertRaises(ValueError):r.side_regions.setflags(write=True)
            self.assertIsNot(n._tree,r._tree)

    def test_concurrent_queries(self):
        n=square_network();t=PG.polyline([[1,0],[1,1]],frame_id='plane')
        def call(i):return n.frames().length_m.tobytes(),n.validate_trace(t,left_region_id='left',right_region_id='right')
        with ThreadPoolExecutor(4) as pool:r=list(pool.map(call,range(12)))
        self.assertTrue(all(x==r[0] for x in r))

    def test_frame_query_budget_and_cancellation(self):
        n=square_network();b=WorkBudget(10)
        with self.assertRaises(MemoryLimitError):n.frames(budget=b)
        self.assertEqual(b.reserved_bytes,0)
        e=threading.Event();e.set()
        with self.assertRaises(CancelledError):n.motion({},[0,0],cancel=e)

    def test_identity_captures_geometry_and_plate_membership(self):
        d,r=parts();a=build(d,r);b=build(d,(r[0],replace(r[1],plate_id='another')))
        self.assertNotEqual(a.network_id,b.network_id)
        self.assertEqual(a.network_id,build(d,r).network_id)

    def test_statistics_are_detached(self):
        n=square_network();s=n.statistics;s['unique_segments']=-1
        self.assertEqual(n.statistics['unique_segments'],7)
        self.assertGreater(n.retained_bytes_estimate,n.nbytes)

    def test_storage_round_trip_and_duplicate_payload(self):
        for n in (square_network(),sphere_network()):
            with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'b.db',StoreLimits(4096,8<<20,32<<20)) as s:
                save_boundary_network(n,s);count=s.statistics()['unique_chunks'];save_boundary_network(n,s)
                self.assertEqual(s.statistics()['unique_chunks'],count)
                r=load_boundary_network(s,n.network_id);self.assertEqual(r.network_id,n.network_id)
                assert_array_equal(r.frames().tangent,n.frames().tangent)
                self.assertIsNone(load_boundary_network(s,'a'*64))

    def test_corrupt_snapshot_rejected(self):
        n=square_network()
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'b.db',StoreLimits(4096,8<<20,32<<20)) as s:
            save_boundary_network(n,s);s._db.execute("UPDATE chunks SET payload=?",(b'bad',))
            with self.assertRaises(StoreError):load_boundary_network(s,n.network_id)

    def test_wrong_metadata_even_with_recomputed_checksum(self):
        n=square_network()
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'b.db',StoreLimits(4096,8<<20,32<<20)) as s:
            save_boundary_network(n,s)
            row=s._db.execute('SELECT body FROM snapshots').fetchone()[0];m=json.loads(row)
            m['metadata']['regions'][0]['plate_id']='changed'
            b=json.dumps(m,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            s._db.execute('UPDATE snapshots SET body=?,digest=?',(b,hashlib.sha256(b).hexdigest()))
            with self.assertRaises(GeometryError):load_boundary_network(s,n.network_id)

    def test_backup_restores_without_original(self):
        n=square_network()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'b.db'
            with ArrayStore(path,StoreLimits(4096,8<<20,32<<20)) as s:
                save_boundary_network(n,s);backup=s.backup_to(Path(tmp)/'backup.db')
            path.unlink()
            with ArrayStore(backup,StoreLimits(4096,8<<20,32<<20)) as s:
                self.assertEqual(load_boundary_network(s,n.network_id).network_id,n.network_id)

    def test_fresh_process_restoration(self):
        n=square_network()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'b.db'
            with ArrayStore(path,StoreLimits(4096,8<<20,32<<20)) as s:save_boundary_network(n,s)
            code="""from atlas_tectonics import load_boundary_network
from atlas_tectonics.storage import ArrayStore,StoreLimits
import sys
with ArrayStore(sys.argv[1],StoreLimits(4096,8<<20,32<<20)) as s:
 n=load_boundary_network(s,sys.argv[2]);print(n.network_id)
"""
            env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1')
            p=subprocess.run([sys.executable,'-B','-c',code,str(path),n.network_id],env=env,text=True,capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),n.network_id)

    def test_execution_identity_guards_boundary_implementation(self):
        import atlas_tectonics.boundaries as module
        context=ExecutionContext()
        with mock.patch.object(module,'_METHOD','silently changed method'):
            with self.assertRaises(ValueError):context.verify()
        context.verify()

    def test_input_geometry_not_modified_by_build(self):
        d,r=parts();before=[d.wkb]+[x.geometry.wkb for x in r];build(d,r)
        self.assertEqual(before,[d.wkb]+[x.geometry.wkb for x in r])


class AdditionalBoundaryChallenges(unittest.TestCase):
    def test_index_copy_admitted_before_allocation(self):
        n=square_network();ids=np.zeros(4096,dtype='i8');b=WorkBudget(16)
        with mock.patch('numpy.array',side_effect=AssertionError('copied before admission')):
            with self.assertRaises(MemoryLimitError):n.frames(ids,budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_wrong_velocity_shape_refused_before_capture(self):
        n=square_network()
        with mock.patch('atlas_tectonics.boundaries.read_array',side_effect=AssertionError('copied oversized input')):
            with self.assertRaises(GeometryError):n.motion({'plate-A':np.zeros((100,3)),'plate-B':[0,0]},[0,0])

    def test_junction_limit_and_cancel(self):
        n=square_network();e=threading.Event();e.set();b=WorkBudget(16)
        with self.assertRaises(CancelledError):n.junction(0,cancel=e)
        with self.assertRaises(MemoryLimitError):n.junction(0,budget=b)
        with self.assertRaises(GeometryError):n.junction(0,limits=GeometryLimits(max_overlay_pairs=1))
        self.assertEqual(b.reserved_bytes,0)

    def test_long_bent_trace_has_correct_order(self):
        a=PG.polygon([[0,0],[3,0],[3,1],[1,1],[1,3],[0,3]],frame_id='plane')
        n=build(box(0,0,3,3),(Region('a','A',a),Region('b','B',box(1,1,3,3))))
        line=PG.polyline([[3,1],[1,1],[1,3]],frame_id='plane')
        uses=n.validate_trace(line,left_region_id='a',right_region_id='b')
        self.assertEqual(len(uses),2)
        self.assertEqual(n.edge(uses[0][0],reverse=uses[0][1]<0).start,(3,1))
        self.assertEqual(n.edge(uses[1][0],reverse=uses[1][1]<0).end,(1,3))

    def test_distinct_compatible_chart_identities(self):
        c2=SphericalChart(S,(0,0,1),.1)
        n=build(sphere_region(-.5,-.5,.5,.5),
            (Region('a','A',sphere_region(-.5,-.5,0,.5)),Region('b','B',sphere_region(0,-.5,.5,.5,c2))))
        self.assertEqual(len(n.interplate_edges),1)
        self.assertNotEqual(n.regions[0].geometry.chart.identity,n.regions[1].geometry.chart.identity)

    def test_inexact_reprojection_not_silently_joined(self):
        xy=np.array([[-.5,-.5],[0,-.5],[.5,-.5],[.5,.5],[0,.5],[-.5,.5]])
        u=CH._unproject(xy);c2=SphericalChart(S,(0,.1,1))
        d=SG.polygon(u,chart=CH);a=SG.polygon(u[[0,1,4,5]],chart=CH)
        b=SG.polygon(u[[1,2,3,4]],chart=c2)
        with self.assertRaises(GeometryError):build(d,(Region('a','A',a),Region('b','B',b)))

    def test_rotation_equivariance_of_verified_spherical_sides(self):
        xy=np.array([[-.5,-.5],[0,-.5],[.5,-.5],[.5,.5],[0,.5],[-.5,.5]])
        u=CH._unproject(xy);q=Rotation.from_axis_angle([1,3,-2],.8)
        c2=SphericalChart(S,tuple(q.apply([0,0,1])))
        results=[]
        for chart,points in ((CH,u),(c2,q.apply(u))):
            n=build(SG.polygon(points,chart=chart),
                (Region('a','A',SG.polygon(points[[0,1,4,5]],chart=chart)),
                 Region('b','B',SG.polygon(points[[1,2,3,4]],chart=chart))))
            i=n.interplate_edges[0]
            results.append(n.frames([i],reverse=n.edge(i).left_region_id!='a'))
        a,b=results
        assert_allclose(q.apply(a.position_m),b.position_m,rtol=RTOL,atol=ATOL)
        assert_allclose(q.apply(a.tangent),b.tangent,rtol=RTOL,atol=ATOL)
        assert_allclose(q.apply(a.right_normal),b.right_normal,rtol=RTOL,atol=ATOL)

    def test_shuffled_rational_grid_independent_graph(self):
        for nx,ny in ((3,2),(5,4)):
            regions=[]
            for i in range(nx):
                for j in range(ny):regions.append(Region(f'{i}:{j}',f'{i}:{j}',box(i,j,i+1,j+1)))
            np.random.default_rng(14).shuffle(regions)
            n=build(box(0,0,nx,ny),regions)
            self.assertEqual(n.vertex_count,(nx+1)*(ny+1))
            self.assertEqual(n.edge_count,nx*(ny+1)+ny*(nx+1))
            expected=set()
            for i in range(nx):
                for j in range(ny):
                    if i+1<nx:expected.add(tuple(sorted((f'{i}:{j}',f'{i+1}:{j}'))))
                    if j+1<ny:expected.add(tuple(sorted((f'{i}:{j}',f'{i}:{j+1}'))))
            self.assertEqual(set(n.adjacency()),expected)

    def test_changed_boundary_geometry_requires_new_network(self):
        a=square_network()
        b=build(box(),(Region('left','plate-A',box(0,0,.75,1)),Region('right','plate-B',box(.75,0,2,1))))
        self.assertNotEqual(a.network_id,b.network_id)
        self.assertEqual(a.edge(a.interplate_edges[0]).start,(1,0))
        self.assertEqual(b.edge(b.interplate_edges[0]).start,(.75,0))

    def test_no_plate_motion_inferred_from_patch_seam(self):
        n=sphere_network(same_plate=True)
        r=n.motion({},[0,0,0]);self.assertEqual(r.values_m_s.shape,(0,5))

    def test_motion_duplicate_edges_rejected(self):
        n=square_network();i=n.interplate_edges[0]
        with self.assertRaises(GeometryError):n.motion({'plate-A':[0,0],'plate-B':[1,0]},[0,0],indices=[i,i])

    def test_trace_limit_checked(self):
        n=square_network();g=PG.polyline([[1,.1],[1,.5],[1,.9]],frame_id='plane')
        with self.assertRaises(GeometryError):n.validate_trace(g,left_region_id='left',right_region_id='right',limits=GeometryLimits(max_vertices=2))


if __name__=='__main__':unittest.main()
