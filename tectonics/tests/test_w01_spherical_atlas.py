"""Independent whole-sphere fixtures and combined stage-3B contracts.

No old tolerance, fixture or test is changed. Closed-form octant/cube symmetries,
known sign ownership and explicit topology checks are independent of the native
membership predicates. Indexed-vs-exhaustive tests are integration evidence.
"""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from dataclasses import FrozenInstanceError, replace
import copy
import hashlib
import itertools
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
from atlas_tectonics import (SphericalFrame, SphericalChart, SphericalGeometry,
    SphericalPatch, SphericalAtlas, build_spherical_atlas as build,
    stitch_spherical_networks as stitch, save_spherical_atlas as save,
    load_spherical_atlas as load, Rotation, GeometryError, GeometryLimits, TectonicsError,
    BoundaryRegion, build_boundary_network)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.spherical_atlas import _restore_atlas

CASE = json.loads((Path(__file__).resolve().parents[1]/'cases/w01_spherical_atlas.json').read_text())
ATOL = CASE['acceptance']['angular_absolute_rad']; RTOL = CASE['acceptance']['relative_tolerance']
SPHERE = SphericalFrame(2.,'test-world')


def octants(*, sphere=SPHERE, all_one=False, seven_one=False, chart_shift=0.):
    vertices={'px':(1.,0,0),'nx':(-1.,0,0),'py':(0,1.,0),'ny':(0,-1.,0),'pz':(0,0,1.),'nz':(0,0,-1.)}
    patches=[]
    for sx,sy,sz in itertools.product((-1,1),repeat=3):
        ids=[('p' if sx>0 else 'n')+'x',('p' if sy>0 else 'n')+'y',('p' if sz>0 else 'n')+'z']
        if sx*sy*sz<0:ids[1],ids[2]=ids[2],ids[1]
        name=''.join('p' if s>0 else 'n' for s in (sx,sy,sz))
        plate='E' if sx>0 else 'W'
        if all_one:plate='world'
        if seven_one:plate='small' if name=='ppp' else 'large'
        chart=SphericalChart(sphere,(sx*(1+chart_shift),sy,sz))
        patches.append(SphericalPatch(name,plate,plate,tuple(ids),chart))
    return vertices,tuple(patches)


def refine(vertices,patches,which=None):
    vertices=dict(vertices);out=[]
    for p in patches:
        if which is not None and p.patch_id not in which:
            out.append(p);continue
        ids=p.vertex_ids
        if len(ids)!=3 or p.holes:raise ValueError('fixture refinement needs triangles')
        centre=np.sum([vertices[v] for v in ids],axis=0);centre/=np.linalg.norm(centre)
        key='centre-'+p.patch_id;vertices[key]=centre
        for j,(a,b) in enumerate(zip(ids,ids[1:]+ids[:1])):
            out.append(replace(p,patch_id=p.patch_id+str(j),vertex_ids=(a,b,key)))
    return vertices,tuple(out)


def cube_tiles(n=1,*,sphere=SPHERE):
    vertices={};patches=[]
    for axis in range(3):
        for sign in (-1,1):
            c=np.eye(3)[axis]*sign
            e=np.eye(3)[(axis+1)%3];north=np.cross(c,e)
            chart=SphericalChart(sphere,tuple(c))
            for i in range(n):
                for j in range(n):
                    ids=[]
                    for u,v in ((i,j),(i+1,j),(i+1,j+1),(i,j+1)):
                        raw=n*c+(2*u-n)*e+(2*v-n)*north
                        key='v'+','.join(str(int(x)) for x in raw)
                        # Scaling differences across tiles do not occur in this fixture.
                        vertices[key]=tuple(raw);ids.append(key)
                    name=f'{axis}{sign}_{i}_{j}'
                    plate=f'face{axis}{sign}'
                    patches.append(SphericalPatch(name,plate,plate,tuple(ids),chart))
    return vertices,tuple(patches)


def network_sources(atlas):
    networks={};bindings={};mapping={}
    points=atlas.vertex_directions
    for p in atlas.patches:
        n=atlas.local_network(p.patch_id);networks[p.patch_id]=n
        dirs=n.domain.chart._unproject(n.vertex_xy)
        indices=np.argmin(np.linalg.norm(dirs[:,None,:]-points[None,:,:],axis=2),axis=1)
        assert np.max(np.linalg.norm(dirs-points[indices],axis=1))<1e-13
        bindings[p.patch_id]=tuple(atlas.vertex_ids[i] for i in indices)
        mapping[(p.patch_id,p.patch_id)]=p.region_id
    return networks,bindings,mapping


class GlobalGeometry(unittest.TestCase):
    def test_octant_closed_area_and_topology(self):
        a=build(SPHERE,*octants())
        self.assertEqual(a.vertex_count,6);self.assertEqual(a.edge_count,12)
        self.assertEqual(a.statistics['euler_characteristic'],2)
        self.assertEqual(a.statistics['unpaired_edges'],0)
        assert_allclose(a.patch_areas_sr,np.full(8,math.pi/2),atol=ATOL,rtol=RTOL)
        self.assertAlmostEqual(sum(a.areas().values()),16*math.pi,places=12)

    def test_cube_faces_independent_symmetric_area(self):
        a=build(SPHERE,*cube_tiles())
        self.assertEqual((a.vertex_count,a.edge_count,len(a.patches)),(8,12,6))
        assert_allclose(a.patch_areas_sr,np.full(6,2*math.pi/3),atol=ATOL,rtol=RTOL)

    def test_cube_subdivision_preserves_face_areas(self):
        coarse=build(SPHERE,*cube_tiles());fine=build(SPHERE,*cube_tiles(3))
        for p,area in coarse.areas().items():self.assertAlmostEqual(fine.areas()[p],area,places=11)
        for p,length in coarse.perimeters().items():self.assertAlmostEqual(fine.perimeters()[p],length,places=11)
        self.assertEqual(coarse.adjacency(),fine.adjacency())

    def test_plate_greater_than_hemisphere(self):
        a=build(SPHERE,*octants(seven_one=True))
        self.assertAlmostEqual(a.areas()['large']/4,7*math.pi/2,places=12)
        self.assertGreater(a.areas()['large'],2*math.pi*4)

    def test_one_plate_covers_whole_sphere_no_false_boundaries(self):
        a=build(SPHERE,*octants(all_one=True))
        self.assertEqual(a.adjacency(),());self.assertEqual(a.interplate_edges,())
        self.assertEqual(a.perimeters(),{'world':0.})
        self.assertAlmostEqual(a.areas()['world'],16*math.pi)
        with a.index() as index:
            self.assertEqual(set(index.query(a.vertex_directions).pairs[:,1]),{0})

    def test_disconnected_region_identity(self):
        v,p=octants()
        p=tuple(replace(f,region_id='islands' if f.patch_id in ('ppp','nnn') else f.patch_id,
                        plate_id='islands' if f.patch_id in ('ppp','nnn') else 'ocean') for f in p)
        a=build(SPHERE,v,p)
        self.assertAlmostEqual(a.areas(by_plate=False)['islands'],4*math.pi)
        self.assertIn(('islands','ocean'),a.adjacency())

    def test_region_hole_as_surrounding_patches(self):
        a=build(SPHERE,*octants(seven_one=True))
        # The complement of one small octant is a valid connected large region.
        self.assertEqual(a.adjacency(),(('large','small'),))
        self.assertAlmostEqual(a.perimeters()['small'],3*math.pi)
        self.assertAlmostEqual(a.perimeters()['large'],3*math.pi)

    def test_holed_patch_and_filled_hole(self):
        v,p=octants();v=dict(v);target=next(x for x in p if x.patch_id=='ppp')
        # An inner triangle creates a true holed local patch, plus its filler.
        inner=[]
        for i,xyz in enumerate(((3.,1,1),(1,3.,1),(1,1,3.))):
            name='h'+str(i);v[name]=xyz;inner.append(name)
        hole=tuple(reversed(inner))
        ring=replace(target,holes=(hole,))
        filler=SphericalPatch('holefill','other','other',tuple(inner),target.chart)
        changed=tuple(ring if f is target else f for f in p)+(filler,)
        a=build(SPHERE,v,changed)
        self.assertEqual(a.statistics['euler_characteristic'],2)
        self.assertAlmostEqual(sum(a.areas().values()),16*math.pi,places=11)
        with a.index() as idx:
            hits=idx.query([[1,1,1]])
            self.assertEqual(hits.owner_ids[hits.pairs[0,1]],'other')

    def test_chart_change_keeps_physical_identity_and_edges(self):
        a=build(SPHERE,*octants());b=build(SPHERE,*octants(chart_shift=.3))
        self.assertEqual(a.geometry_id,b.geometry_id)
        self.assertEqual(a.edge_ids,b.edge_ids)
        self.assertNotEqual(a.atlas_id,b.atlas_id)
        self.assertEqual(a.areas(),b.areas())
        assert_array_equal(a.frames().tangent,b.frames().tangent)

    def test_cyclic_ring_and_input_order_identity(self):
        v,p=octants();a=build(SPHERE,v,p)
        p=tuple(replace(x,vertex_ids=x.vertex_ids[1:]+x.vertex_ids[:1]) for x in reversed(p))
        b=build(SPHERE,dict(reversed(list(v.items()))),p)
        self.assertEqual(a.atlas_id,b.atlas_id)

    def test_internal_refinement_does_not_create_plate_boundaries(self):
        v,p=octants();a=build(SPHERE,v,p);b=build(SPHERE,*refine(v,p))
        self.assertEqual(a.adjacency(),b.adjacency())
        self.assertEqual({a.edge_ids[i] for i in a.interplate_edges},{b.edge_ids[i] for i in b.interplate_edges})
        for name in a.areas():self.assertAlmostEqual(a.areas()[name],b.areas()[name],places=11)
        self.assertEqual(a.perimeters(),b.perimeters())

    def test_global_rotation_preserves_metrics(self):
        v,p=octants();a=build(SPHERE,v,p);rot=Rotation.from_axis_angle([1,2,3],1.2)
        v2={k:rot.apply(x) for k,x in v.items()}
        p2=tuple(replace(x,chart=SphericalChart(SPHERE,tuple(rot.apply(x.chart.centre)))) for x in p)
        b=build(SPHERE,v2,p2)
        assert_allclose(b.patch_areas_sr,a.patch_areas_sr,rtol=RTOL,atol=ATOL)
        for name in a.perimeters():self.assertAlmostEqual(a.perimeters()[name],b.perimeters()[name],places=11)

    def test_radius_scaling_and_frame_identity(self):
        a=build(SPHERE,*octants());s=SphericalFrame(6.,'test-world');b=build(s,*octants(sphere=s))
        for name in a.areas():self.assertAlmostEqual(b.areas()[name]/a.areas()[name],9)
        for name in a.perimeters():self.assertAlmostEqual(b.perimeters()[name]/a.perimeters()[name],3)
        self.assertNotEqual(a.geometry_id,b.geometry_id)

    def test_edge_directions_and_opposite_region_uses(self):
        a=build(SPHERE,*octants())
        for i in range(a.edge_count):
            edge=a.edge(i);back=a.edge(i,reverse=True)
            self.assertEqual(edge.start,back.end);self.assertEqual(edge.end,back.start)
            self.assertEqual(edge.left_plate_id,back.right_plate_id)
            self.assertEqual(edge.boundary_id,back.boundary_id)
            l,r=a.side_patches[i];self.assertNotEqual(l,r)

    def test_junctions_have_full_cyclic_ownership(self):
        a=build(SPHERE,*octants())
        for i in range(a.vertex_count):
            j=a.junction(i);self.assertEqual(j.degree,4)
            self.assertNotIn(None,j.sector_region_ids)
            for k,(edge,sign) in enumerate(zip(j.edge_indices,j.signs)):
                here=a.edge(edge,reverse=sign<0)
                self.assertEqual(j.sector_region_ids[k],here.left_region_id)

    def test_frames_are_orthonormal_on_sphere(self):
        a=build(SPHERE,*octants())
        f=a.frames();u=f.position_m/2
        assert_allclose(np.linalg.norm(f.tangent,axis=1),1,atol=ATOL)
        assert_allclose(np.sum(f.tangent*u,axis=1),0,atol=ATOL)
        assert_allclose(np.cross(f.tangent,u),f.right_normal,atol=ATOL)
        assert_allclose(f.length_m,np.full(12,math.pi),atol=ATOL)

    def test_frames_reverse_and_endpoint_fractions(self):
        a=build(SPHERE,*octants())
        for t in (0.,.1,.5,.9,1.):
            f=a.frames(fraction=t);b=a.frames(reverse=True,fraction=1-t)
            assert_allclose(f.position_m,b.position_m,atol=ATOL)
            assert_allclose(f.tangent,-b.tangent,atol=ATOL)
            assert_allclose(f.right_normal,-b.right_normal,atol=ATOL)

    def test_motion_reverse_preserves_opening(self):
        a=build(SPHERE,*octants());velocity={'E':[1.,2,3],'W':[-1.,2,1]}
        f=a.motion(velocity,[0,0,0]);b=a.motion(velocity,[0,0,0],reverse=True)
        assert_allclose(f.opening_m_s,b.opening_m_s,atol=ATOL)
        assert_allclose(f.tangential_m_s,b.tangential_m_s,atol=ATOL)
        assert_allclose(f.values_m_s[:,4],-b.values_m_s[:,4],atol=ATOL)

    def test_uniform_plate_velocity_no_relative_motion(self):
        a=build(SPHERE,*octants());f=a.motion({'E':[2,3,4],'W':[2,3,4]},[2,3,4])
        assert_array_equal(f.values_m_s,np.zeros_like(f.values_m_s))

    def test_random_convex_hull_sphere_partition(self):
        from scipy.spatial import ConvexHull
        rng=np.random.default_rng(932);pts=rng.normal(size=(32,3));pts/=np.linalg.norm(pts,axis=1)[:,None]
        hull=ConvexHull(pts);self.assertTrue(np.all(hull.equations[:,-1]<0))
        v={str(i):p for i,p in enumerate(pts)};patches=[]
        for i,face in enumerate(hull.simplices):
            ids=list(face)
            if np.linalg.det(pts[ids])<0:ids[1],ids[2]=ids[2],ids[1]
            chart=SphericalChart(SPHERE,tuple(pts[ids].sum(axis=0)))
            patches.append(SphericalPatch(str(i),'world','world',tuple(map(str,ids)),chart))
        a=build(SPHERE,v,tuple(patches))
        self.assertAlmostEqual(sum(a.areas().values()),16*math.pi,places=11)
        with a.index() as idx:
            q=rng.normal(size=(100,3));self.assertEqual(len(idx.query(q).pairs),100)


class InvalidAtlas(unittest.TestCase):
    def setUp(self):self.v,self.p=octants()
    def test_missing_patch(self):
        with self.assertRaisesRegex(GeometryError,'unpaired'):build(SPHERE,self.v,self.p[:-1])
    def test_duplicate_patch_id(self):
        with self.assertRaises(GeometryError):build(SPHERE,self.v,self.p+(self.p[0],))
    def test_overlapping_duplicate_face(self):
        with self.assertRaisesRegex(GeometryError,'same-side'):build(SPHERE,self.v,self.p+(replace(self.p[0],patch_id='extra'),))
    def test_reversed_single_face(self):
        p=(replace(self.p[0],vertex_ids=tuple(reversed(self.p[0].vertex_ids))),)+self.p[1:]
        with self.assertRaises(GeometryError):build(SPHERE,self.v,p)
    def test_nonconforming_seam(self):
        p=self.p[0];a,b,c=p.vertex_ids;self.v['mid']=np.array(self.v[a])+self.v[b]
        wrong=(replace(p,vertex_ids=(a,'mid',b,c)),)+self.p[1:]
        with self.assertRaisesRegex(GeometryError,'unpaired'):build(SPHERE,self.v,wrong)
    def test_unknown_vertex(self):
        with self.assertRaises(GeometryError):build(SPHERE,self.v,(replace(self.p[0],vertex_ids=('unknown',*self.p[0].vertex_ids[1:])),)+self.p[1:])
    def test_unused_vertex(self):
        self.v['unused']=(1.,1,1)
        with self.assertRaisesRegex(GeometryError,'unused'):build(SPHERE,self.v,self.p)
    def test_duplicate_position_distinct_id(self):
        self.v['duplicate']=self.v['px']
        with self.assertRaisesRegex(GeometryError,'duplicate geometric'):build(SPHERE,self.v,self.p)
    def test_region_conflicting_plate(self):
        p=(replace(self.p[0],region_id='same',plate_id='a'),replace(self.p[1],region_id='same',plate_id='b'))+self.p[2:]
        with self.assertRaises(GeometryError):build(SPHERE,self.v,p)
    def test_incompatible_sphere(self):
        p=(replace(self.p[0],chart=SphericalChart(SphericalFrame(4.,'other'),self.p[0].chart.centre)),)+self.p[1:]
        with self.assertRaises(GeometryError):build(SPHERE,self.v,p)
    def test_chart_horizon(self):
        p=(replace(self.p[0],chart=SphericalChart(SPHERE,(1,1,1))),)+self.p[1:]
        with self.assertRaises(GeometryError):build(SPHERE,self.v,p)
    def test_masks_and_zero_directions(self):
        for value in (np.ma.array([1.,0,0]),[0,0,0],[np.inf,0,0],[True,0,0]):
            with self.subTest(value=str(value)),self.assertRaises(TectonicsError):
                v=dict(self.v,px=value);build(SPHERE,v,self.p)
    def test_repeated_ring_vertex(self):
        with self.assertRaises(GeometryError):replace(self.p[0],vertex_ids=('px','py','px'))
    def test_invalid_metadata_and_types(self):
        for value in (None,{},(),[1,2,3]):
            with self.subTest(value=value),self.assertRaises(GeometryError):build(SPHERE,self.v,value)
    def test_unresolved_small_edge(self):
        v=dict(self.v);v['py']=(1.,1e-16,0)
        with self.assertRaises(GeometryError):build(SPHERE,v,self.p)
    def test_antipodal_edge(self):
        p=self.p[0];wrong=replace(p,vertex_ids=('px','nx','pz'))
        with self.assertRaises(GeometryError):build(SPHERE,self.v,(wrong,)+self.p[1:])
    def test_moved_vertex_creating_fold_is_refused(self):
        v=dict(self.v);v['px']=(-.2,1.,1.)
        with self.assertRaises(GeometryError):build(SPHERE,v,self.p)

    def test_short_nonzero_but_duplicate_junction_ray_refused(self):
        from atlas_tectonics.spherical_atlas import _vertex_links
        points=np.array([[0.,0,1.],[1.,0,0],[1.,0,0]])
        edges=np.array([[0,1],[0,2],[1,2]])
        sides=np.array([[0,1],[1,0],[0,1]])
        with self.assertRaises(GeometryError):_vertex_links(points,edges,sides,2,1e-14,None)

    def test_all_reversed_sheet_refused(self):
        with self.assertRaises(GeometryError):build(SPHERE,self.v,tuple(replace(p,vertex_ids=p.vertex_ids[::-1]) for p in self.p))
    def test_bad_hole_orientation(self):
        p=self.p[-1];v=dict(self.v,h0=(3,1,1),h1=(1,3,1),h2=(1,1,3))
        with self.assertRaises(GeometryError):build(SPHERE,v,self.p[:-1]+(replace(p,holes=(('h0','h1','h2'),)),))
    def test_nonfinite_planet_area(self):
        sphere=SphericalFrame(1e200,'test-world')
        with self.assertRaises(GeometryError):build(sphere,*octants(sphere=sphere))
    def test_bad_resolution_and_source_provenance(self):
        for value in (0.,1.,np.nan,True):
            with self.subTest(value=value),self.assertRaises(TectonicsError):build(SPHERE,self.v,self.p,angular_resolution_rad=value)
        with self.assertRaises(GeometryError):build(SPHERE,self.v,self.p,source_bindings={'a':float('nan')})


class AtlasQueries(unittest.TestCase):
    def setUp(self):self.a=build(SPHERE,*octants())
    def test_independent_octant_sign_ownership(self):
        rng=np.random.default_rng(827);q=rng.normal(size=(400,3))
        with self.a.index() as idx:r=idx.query(q)
        self.assertEqual(len(r.pairs),len(q))
        for i,owner in r.pairs:self.assertEqual(r.owner_ids[owner],'E' if q[i,0]>0 else 'W')
    def test_poles_and_longitude_seam(self):
        q=np.array([[0,0,1],[0,0,-1],[-1,0,0],[-1,1e-8,0],[-1,-1e-8,0]])
        with self.a.index() as idx:r=idx.query(q)
        self.assertEqual([r.owner_ids[i] for i in r.pairs[r.pairs[:,0]==0,1]],['E','W'])
        for row in (2,3,4):self.assertEqual([r.owner_ids[i] for i in r.pairs[r.pairs[:,0]==row,1]],['W'])
    def test_every_seam_reports_true_owners(self):
        q=self.a.frames().position_m
        with self.a.index() as idx:r=idx.query(q)
        for i in range(self.a.edge_count):
            edge=self.a.edge(i);names={r.owner_ids[j] for j in r.pairs[r.pairs[:,0]==i,1]}
            self.assertEqual(names,{edge.left_plate_id,edge.right_plate_id})
    def test_refined_patch_layout_same_answers(self):
        v,p=octants();b=build(SPHERE,*refine(v,p));q=np.vstack((self.a.vertex_directions,np.random.default_rng(12).normal(size=(128,3))))
        with self.a.index() as x,b.index() as y:
            r=x.query(q);s=y.query(q);self.assertEqual(r.owner_ids,s.owner_ids);assert_array_equal(r.pairs,s.pairs)
    def test_changed_charts_same_answers(self):
        b=build(SPHERE,*octants(chart_shift=.25));q=np.vstack((self.a.vertex_directions,self.a.frames().position_m))
        with self.a.index() as x,b.index() as y:assert_array_equal(x.query(q).pairs,y.query(q).pairs)
    def test_index_matches_exhaustive(self):
        a=build(SPHERE,*cube_tiles(3));q=np.random.default_rng(672).normal(size=(200,3));pairs=[]
        owners=a.plate_ids
        for p,g in zip(a.patches,a.regions):
            for i in np.flatnonzero(g.geometry.classify(q)>=0):pairs.append((i,owners.index(p.plate_id)))
        with a.index() as idx:r=idx.query(q)
        assert_array_equal(r.pairs,np.unique(pairs,axis=0))
        self.assertLess(r.candidate_pairs,r.exhaustive_pairs//4)
    def test_by_region_and_plate_agree_with_catalogue(self):
        v,p=octants();p=tuple(replace(x,region_id=x.patch_id) for x in p);a=build(SPHERE,v,p)
        q=np.array([[1.,1,1]])
        with a.index() as idx:
            r=idx.query(q,by_plate=False);self.assertEqual(r.owner_ids[r.pairs[0,1]],'ppp')
            r=idx.query(q);self.assertEqual(r.owner_ids[r.pairs[0,1]],'E')
    def test_bounded_query_batches(self):
        q=np.random.default_rng(3).normal(size=(100,3))
        with self.a.index() as idx:
            together=idx.query(q);parts=list(idx.query_batches([q[:50],q[50:]]))
            rows=parts[1].pairs.copy();rows[:,0]+=50
            assert_array_equal(together.pairs,np.vstack((parts[0].pairs,rows)))
    def test_closed_index(self):
        idx=self.a.index();idx.close();idx.close()
        with self.assertRaises(GeometryError):idx.query([[1,1,1]])
    def test_concurrent_index_reads(self):
        q=np.random.default_rng(11).normal(size=(80,3))
        with self.a.index() as idx,ThreadPoolExecutor(3) as pool:
            result=list(pool.map(lambda _:idx.query(q).pairs.tobytes(),range(6)))
            self.assertEqual(len(set(result)),1)
    def test_query_limit(self):
        with self.a.index(limits=GeometryLimits(max_hits=1)) as idx:
            with self.assertRaises(GeometryError):idx.query([[0,0,1]])
    def test_query_invalid(self):
        with self.a.index() as idx:
            for p in ([[0,0,0]],[],[[1,2]],np.ma.array([[1,0,0]])):
                with self.subTest(p=str(p)),self.assertRaises(ValueError):idx.query(p)
            with self.assertRaises(GeometryError):idx.query([[1,1,1]],angular_tolerance_rad=.1)
    def test_boundary_point_near_miss_not_widened(self):
        q=[[1e-8,1,1],[-1e-8,1,1]]
        with self.a.index() as idx:r=idx.query(q)
        self.assertEqual(len(r.pairs),2)
        self.assertEqual([r.owner_ids[i] for i in r.pairs[:,1]],['E','W'])
    def test_short_interplate_arc_midpoint_and_near_misses(self):
        for epsilon in (1e-6,1e-9,1e-12):
            with self.subTest(epsilon=epsilon):
                v,p=octants();v=dict(v);v['short']=(0.,1.,epsilon);out=[]
                for face in p:
                    ids=[]
                    for a,b in zip(face.vertex_ids,face.vertex_ids[1:]+face.vertex_ids[:1]):
                        ids.append(a)
                        if {a,b}=={'py','pz'}:ids.append('short')
                    out.append(replace(face,vertex_ids=tuple(ids)))
                a=build(SPHERE,v,tuple(out))
                edge=next(i for i,pair in enumerate(a.edge_vertices)
                          if {a.vertex_ids[j] for j in pair}=={'py','short'})
                point=a.frames([edge]).position_m
                with a.index() as idx:
                    hit=idx.query(point)
                    self.assertEqual({hit.owner_ids[i] for i in hit.pairs[:,1]},{'E','W'})
                self.assertAlmostEqual(a.frames([edge]).length_m[0],2*math.atan(epsilon),delta=1e-15)

    def test_index_close_refuses_active_reader(self):
        started=threading.Event();release=threading.Event()
        original=SphericalGeometry.classify
        def block(geom,*args,**kwargs):
            started.set();release.wait(5)
            return original(geom,*args,**kwargs)
        with self.a.index() as idx,ThreadPoolExecutor(1) as pool:
            with mock.patch.object(SphericalGeometry,'classify',block):
                future=pool.submit(idx.query,[[1,1,1]])
                self.assertTrue(started.wait(5))
                try:
                    with self.assertRaises(GeometryError):idx.close()
                finally:release.set()
                self.assertEqual(len(future.result(5).pairs),1)

    def test_closed_stream_does_not_consume_more_input(self):
        seen=[]
        def requests():
            for n in range(4):seen.append(n);yield [[1,1,1]]
        with self.a.index() as idx:
            iterator=idx.query_batches(requests());next(iterator);iterator.close()
            self.assertEqual(seen,[0])

    def test_patch_metadata_immutable_in_index(self):
        with self.a.index() as idx:
            with self.assertRaises(GeometryError):idx._atlas=build(SPHERE,*octants(all_one=True))


class Stage3Stitching(unittest.TestCase):
    def setUp(self):self.a=build(SPHERE,*octants());self.n,self.b,self.r=network_sources(self.a)
    def test_existing_local_networks_join_global(self):
        v=dict(zip(self.a.vertex_ids,self.a.vertex_directions));joined=stitch(self.n,v,self.b,region_bindings=self.r)
        self.assertEqual(joined.adjacency(),self.a.adjacency())
        self.assertEqual(joined.areas(),self.a.areas())
        self.assertEqual(set(joined.edge_ids),set(self.a.edge_ids))
        self.assertTrue(all(row['maximum_attachment_error_rad']<2e-14 for row in joined.descriptor()['source_bindings']['networks']))
    def test_binding_not_nearest_welding(self):
        b=dict(self.b);name=next(iter(b));v=list(b[name]);v[0],v[1]=v[1],v[0];b[name]=tuple(v)
        with self.assertRaises(GeometryError):stitch(self.n,dict(zip(self.a.vertex_ids,self.a.vertex_directions)),b)
    def test_incorrect_registry_not_snapped(self):
        v=dict(zip(self.a.vertex_ids,self.a.vertex_directions));v['px']=(1,1e-7,0)
        with self.assertRaisesRegex(GeometryError,'disagree'):stitch(self.n,v,self.b)
    def test_rotated_registry_restitch_preserves_bytes(self):
        v,p=octants();rot=Rotation.from_axis_angle([1,2,3],.723)
        v={k:rot.apply(x) for k,x in v.items()}
        p=tuple(replace(f,chart=SphericalChart(SPHERE,tuple(rot.apply(f.chart.centre)))) for f in p)
        original=build(SPHERE,v,p)
        for _ in range(3):
            n,b,r=network_sources(original)
            current=stitch(n,dict(zip(original.vertex_ids,original.vertex_directions)),b,region_bindings=r)
            self.assertEqual(current.vertex_directions.tobytes(),original.vertex_directions.tobytes())
            self.assertEqual(set(current.edge_ids),set(original.edge_ids))
            original=current

    def test_registry_direct_rebuild_preserves_bytes(self):
        v,p=cube_tiles(3);original=build(SPHERE,v,p)
        for _ in range(3):
            current=build(SPHERE,dict(zip(original.vertex_ids,original.vertex_directions)),original.patches)
            self.assertEqual(current.atlas_id,original.atlas_id);original=current

    def test_stitch_registry_limit_before_capture(self):
        v=dict(zip(self.a.vertex_ids,self.a.vertex_directions))
        for i in range(50):v['excess'+str(i)]=[1,1,1]
        with self.assertRaises(GeometryError):stitch(self.n,v,self.b,limits=GeometryLimits(max_vertices=50))

    def test_missing_binding(self):
        b=dict(self.b);del b[next(iter(b))]
        with self.assertRaises(GeometryError):stitch(self.n,dict(zip(self.a.vertex_ids,self.a.vertex_directions)),b)
    def test_duplicate_binding(self):
        b=dict(self.b);name=next(iter(b));b[name]=(b[name][0],)*3
        with self.assertRaises(GeometryError):stitch(self.n,dict(zip(self.a.vertex_ids,self.a.vertex_directions)),b)
    def test_missing_source_patch(self):
        n=dict(self.n);b=dict(self.b);k=next(iter(n));del n[k];del b[k]
        with self.assertRaises(GeometryError):stitch(n,dict(zip(self.a.vertex_ids,self.a.vertex_directions)),b)
    def test_stage3_network_round_trip(self):
        v,p=cube_tiles();a=build(SPHERE,v,p);n,b,r=network_sources(a)
        other=stitch(n,dict(zip(a.vertex_ids,a.vertex_directions)),b,region_bindings=r)
        for name in a.areas():self.assertAlmostEqual(other.areas()[name],a.areas()[name],places=12)
    def test_unknown_region_binding(self):
        with self.assertRaises(GeometryError):stitch(self.n,dict(zip(self.a.vertex_ids,self.a.vertex_directions)),self.b,region_bindings={('bad','bad'):'bad'})


class AtlasResourcesAndStorage(unittest.TestCase):
    def setUp(self):self.a=build(SPHERE,*octants());self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()
    def store(self,name='atlas.db'):
        return ArrayStore(Path(self.tmp.name)/name,StoreLimits(4096,4<<20,16<<20,8192))
    def test_immutable_all_arrays_and_metadata(self):
        for x in (self.a.vertex_directions,self.a.edge_vertices,self.a.side_patches,self.a.patch_areas_sr,self.a.frames().tangent):
            with self.assertRaises(ValueError):x.setflags(write=True)
        a=self.a.vertex_directions;a.shape=(a.size,);self.assertEqual(self.a.vertex_directions.shape,(6,3))
        desc=self.a.descriptor();desc['patches'][0]['plate_id']='bad';self.assertNotEqual(self.a.patches[0].plate_id,'bad')
        with self.assertRaises(FrozenInstanceError):self.a.atlas_id='bad'
    def test_input_mutation_cannot_change_geometry(self):
        v,p=octants();v={k:np.array(x) for k,x in v.items()};a=build(SPHERE,v,p);before=a.vertex_directions.tobytes()
        v['px'][:]=9;self.assertEqual(a.vertex_directions.tobytes(),before)
    def test_pickle_deepcopy_restore(self):
        for a in (copy.deepcopy(self.a),pickle.loads(pickle.dumps(self.a))):
            self.assertEqual(a.atlas_id,self.a.atlas_id)
            self.assertEqual(a.geometry_id,self.a.geometry_id)
            with self.assertRaises(ValueError):a.vertex_directions.setflags(write=True)
    def test_budget_refusal_releases(self):
        b=WorkBudget(100)
        with self.assertRaises(MemoryLimitError):build(SPHERE,*octants(),budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_index_retained_lifetime_and_query_budget(self):
        b=WorkBudget(8<<20)
        with self.a.index(budget=b) as idx:
            retained=b.reserved_bytes;self.assertGreater(retained,0)
            idx.query([[1,1,1]]);self.assertEqual(b.reserved_bytes,retained)
            with self.assertRaises(MemoryLimitError):idx.query([[1,1,1]],budget=WorkBudget(100))
            self.assertEqual(b.reserved_bytes,retained)
        self.assertEqual(b.reserved_bytes,0)
    def test_pre_cancel_all_queries(self):
        cancel=threading.Event();cancel.set();b=WorkBudget(8<<20)
        calls=[lambda:build(SPHERE,*octants(),budget=b,cancel=cancel),lambda:self.a.frames(cancel=cancel),
               lambda:self.a.junction(0,cancel=cancel),lambda:self.a.motion({},[0,0,0],cancel=cancel)]
        for call in calls:
            with self.assertRaises(CancelledError):call()
        with self.a.index(budget=b) as idx:
            with self.assertRaises(CancelledError):idx.query([[1,1,1]],cancel=cancel)
        self.assertEqual(b.reserved_bytes,0)
    def test_cancel_mid_build(self):
        class CountCancel:
            n=0
            def is_set(self):self.n+=1;return self.n>4
        b=WorkBudget(8<<20)
        with self.assertRaises(CancelledError):build(SPHERE,*octants(),budget=b,cancel=CountCancel())
        self.assertEqual(b.reserved_bytes,0)
    def test_saved_restore_immutable(self):
        with self.store() as s:
            save(self.a,s);out=load(s,self.a.atlas_id)
            self.assertEqual(out.descriptor(),self.a.descriptor())
            with self.assertRaises(ValueError):out.edge_vertices.setflags(write=True)
    def test_dedup_and_chart_only_snapshot(self):
        b=build(SPHERE,*octants(chart_shift=.2))
        with self.store() as s:
            save(self.a,s);old=s.statistics()['unique_chunks'];save(b,s)
            self.assertEqual(s.statistics()['unique_chunks'],old)
            self.assertEqual(s.statistics()['snapshots'],2)
    def test_backup_after_original_removed(self):
        with self.store() as s:
            save(self.a,s);path=s.path;backup=s.backup_to(Path(self.tmp.name)/'backup.db')
        path.unlink()
        with ArrayStore(backup,StoreLimits(4096,4<<20,16<<20,8192)) as s:
            self.assertEqual(load(s,self.a.atlas_id).atlas_id,self.a.atlas_id)
    def test_corrupt_chunk_is_error(self):
        with self.store() as s:
            save(self.a,s)
            s._db.execute('UPDATE chunks SET payload=?',(b'bad',))
            with self.assertRaises(StoreError):load(s,self.a.atlas_id)
    def test_missing_chunk_is_error(self):
        with self.store() as s:
            save(self.a,s);s._db.execute('DELETE FROM chunks')
            with self.assertRaises(StoreError):load(s,self.a.atlas_id)
    def test_absent_snapshot_returns_none(self):
        with self.store() as s:self.assertIsNone(load(s,'0'*64))
    def test_tampered_descriptor_not_trusted(self):
        desc=self.a.descriptor();desc['patches'][0]['plate_id']='bad'
        with self.assertRaises(GeometryError):_restore_atlas(desc,self.a._points)
    def test_oversized_or_wrong_restore_payload(self):
        with self.assertRaises(GeometryError):_restore_atlas(self.a.descriptor(),b'bad')
        with self.assertRaises(GeometryError):_restore_atlas(self.a.descriptor(),self.a._points,limits=GeometryLimits(max_vertices=1))
    def test_execution_identity_covers_module(self):
        import atlas_tectonics.spherical_atlas as module
        with ExecutionContext() as c:
            c.verify()
            with mock.patch.object(module,'_AREA_TOLERANCE_SR',1.):
                with self.assertRaises(TectonicsError):c.verify()
    def test_native_spatial_runtime_is_identified(self):
        with ExecutionContext() as context:
            self.assertEqual(len(context._runtime['binaries']['scipy_ckdtree']),64)
            self.assertIn('scipy_spatial',context._runtime['versions'])

    def test_fresh_process_rebuild(self):
        with self.store() as s:save(self.a,s)
        code="""import sys
from atlas_tectonics import load_spherical_atlas
from atlas_tectonics.storage import ArrayStore,StoreLimits
with ArrayStore(sys.argv[1],StoreLimits(4096,4<<20,16<<20,8192)) as store:
 a=load_spherical_atlas(store,sys.argv[2])
 with a.index() as index:
  assert len(index.query([[1,1,1],[-1,1,1]]).pairs)==2
 print(a.atlas_id)
"""
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        out=subprocess.run([sys.executable,'-B','-c',code,str(Path(self.tmp.name)/'atlas.db'),self.a.atlas_id],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(out.returncode,0,out.stderr);self.assertEqual(out.stdout.strip(),self.a.atlas_id)
    def test_frames_invalid_selection(self):
        for x in ([-1],[99],[True],np.array([1.])):
            with self.assertRaises(GeometryError):self.a.frames(x)
        with self.assertRaises(GeometryError):self.a.frames(fraction=2)
    def test_invalid_motion(self):
        with self.assertRaises(GeometryError):self.a.motion({},[0,0,0])
        with self.assertRaises(GeometryError):self.a.motion({'E':[0,0,0],'W':[0,0,0]},[0,0,0],indices=[0,0])
        with self.assertRaises(GeometryError):self.a.motion({'E':[0,0],'W':[0,0]},[0,0,0])
    def test_index_constructor_failure_releases_budget(self):
        b=WorkBudget(8<<20)
        with mock.patch('scipy.spatial.cKDTree',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):self.a.index(budget=b)
        self.assertEqual(b.reserved_bytes,0)


if __name__=='__main__':unittest.main()
