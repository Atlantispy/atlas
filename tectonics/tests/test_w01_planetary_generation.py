"""W01 3C independent mathematical tests plus existing atlas/storage integration.

Independent nearest-site scores, exact symmetry areas and analytic lune widths
check the generation rule; comparing two implementations alone is insufficient.
Prior fixtures and tolerances are unchanged. Temporary stores; no network writes.
"""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from dataclasses import FrozenInstanceError, replace
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
from atlas_tectonics import (SphericalFrame, PlanetPartitionSettings, PlanetaryPartitionPlan,
    PartitionCandidateError, PartitionGenerationError, prepare_planetary_partition as prepare,
    generate_planetary_partition as generate, repatch_planetary_partition as repatch,
    generated_partition_id, GeometryLimits, GeometryError, Rotation,
    save_spherical_atlas as save, load_spherical_atlas as load)
from atlas_tectonics.geometry import _json
from atlas_tectonics.planetary_generation import _draw_sites, _restore_plan
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
from atlas_tectonics.reuse import ExecutionContext

CASE = json.loads((Path(__file__).resolve().parents[1]/'cases/w01_planetary_generation.json').read_text())
ATOL = CASE['acceptance']['angular_absolute_rad']
RTOL = CASE['acceptance']['relative_tolerance']
SPHERE = SphericalFrame(2., 'synthetic-planet')
TETRA = {'a':(1,1,1), 'b':(1,-1,-1), 'c':(-1,1,-1), 'd':(-1,-1,1)}


def build(n=12, seed=72, **kwargs):
    return generate(SPHERE, PlanetPartitionSettings(n, seed), **kwargs)


def binding(atlas): return atlas.descriptor()['source_bindings']['partition_generation']


def directions(n=128):
    rng = np.random.Generator(np.random.PCG64(817))
    points = rng.normal(size=(n,3))
    return points/np.linalg.norm(points, axis=1)[:,None]


def owners(atlas, points):
    with atlas.index() as index:
        hits = index.query(points, angular_tolerance_rad=ATOL)
    out = [set() for _ in points]
    for q, p in hits.pairs: out[int(q)].add(hits.owner_ids[int(p)])
    return out


class MathematicalPartitions(unittest.TestCase):
    def test_one_plate_covers_world(self):
        a=build(1)
        self.assertEqual(len(a.plate_ids),1);self.assertEqual(a.interplate_edges,())
        self.assertEqual(a.adjacency(),());self.assertEqual(list(a.perimeters().values()),[0.])
        self.assertAlmostEqual(sum(a.areas().values()),16*math.pi,places=11)
        self.assertEqual(owners(a,directions(64)),[{a.plate_ids[0]}]*64)

    def test_two_arbitrary_sites_are_hemispheres(self):
        p=prepare(SPHERE,{'a':(1,0,0),'b':(0,0,1)})
        a=p.build()
        assert_allclose(list(a.areas().values()),[8*math.pi]*2,rtol=RTOL,atol=ATOL)
        assert_allclose(list(a.perimeters().values()),[4*math.pi]*2,rtol=RTOL,atol=ATOL)
        for q,actual in zip(directions(),owners(a,directions())):
            self.assertEqual(actual,{'a' if q[0]>q[2] else 'b'})

    def test_two_antipodal_sites_supported(self):
        a=prepare(SPHERE,{'north':(0,0,1),'south':(0,0,-1)}).build()
        self.assertEqual(owners(a,np.eye(3)),[{'north','south'},{'north','south'},{'north'}])

    def test_three_equally_spaced_lunes(self):
        angles=np.arange(3)*2*math.pi/3
        sites={str(i):(math.cos(t),math.sin(t),0.) for i,t in enumerate(angles)}
        a=prepare(SPHERE,sites).build()
        assert_allclose(list(a.areas().values()),np.full(3,16*math.pi/3),atol=ATOL,rtol=RTOL)
        self.assertEqual(a.adjacency(),(('0','1'),('0','2'),('1','2')))
        self.assertEqual(owners(a,np.array([[0,0,1],[0,0,-1]])),[set(sites)]*2)

    def test_three_unequal_lune_areas(self):
        angles=np.array([0.0,0.7,3.2]); sites={str(i):(math.cos(t),math.sin(t),0.) for i,t in enumerate(angles)}
        a=prepare(SPHERE,sites).build();gaps=np.diff(np.r_[angles,2*math.pi])
        # Lune solid angle is twice its longitude width. Its width is half the
        # sum of the two neighbouring site gaps on their common great circle.
        expected=4*(gaps+np.roll(gaps,1))
        assert_allclose(list(a.areas().values()),expected,rtol=RTOL,atol=ATOL)

    def test_three_sites_on_small_circle(self):
        angles=np.array([0.0,1.1,3.6]);z=.8;r=math.sqrt(1-z*z)
        sites={str(i):(r*math.cos(t),r*math.sin(t),z) for i,t in enumerate(angles)}
        a=prepare(SPHERE,sites).build();q=directions()
        s=np.array([sites[k] for k in sorted(sites)])
        expected=[{str(int(i))} for i in np.argmax(q@s.T,axis=1)]
        self.assertEqual(owners(a,q),expected)

    def test_tetrahedron_exact_area(self):
        a=prepare(SPHERE,TETRA).build()
        assert_allclose(list(a.areas().values()),np.full(4,4*math.pi),atol=ATOL,rtol=RTOL)
        self.assertEqual((a.vertex_count,a.edge_count,len(a.patches)),(4,6,4))
        self.assertEqual(len(a.adjacency()),6)

    def test_octahedral_sites_exact_cube_areas(self):
        sites={str(i):q for i,q in enumerate(np.concatenate((np.eye(3),-np.eye(3))))}
        a=prepare(SPHERE,sites).build()
        assert_allclose(list(a.areas().values()),np.full(6,8*math.pi/3),atol=ATOL,rtol=RTOL)
        self.assertEqual((a.vertex_count,a.edge_count,len(a.patches)),(8,12,6))

    def test_closed_coverage_many_counts(self):
        for n in (1,2,3,4,5,6,8,12,32,64):
            with self.subTest(n=n):
                a=build(n,31)
                self.assertEqual(len(a.plate_ids),n)
                self.assertEqual(a.statistics['euler_characteristic'],2)
                self.assertEqual(a.statistics['unpaired_edges'],0)
                self.assertLessEqual(abs(a.statistics['area_residual_sr']),2e-11)
                self.assertTrue(all(x>0 for x in a.areas().values()))

    def test_membership_is_independent_nearest_site_rule(self):
        for n in (1,2,3,4,12,32):
            with self.subTest(n=n):
                a=build(n,31);source=binding(a);sites=np.array(source['site_directions']);q=directions(150)
                scores=q@sites.T
                expected=[{source['site_ids'][int(i)]} for i in np.argmax(scores,axis=1)]
                self.assertEqual(owners(a,q),expected)

    def test_every_seed_owns_its_location(self):
        a=build();s=binding(a)
        self.assertEqual(owners(a,np.array(s['site_directions'])),[{name} for name in s['site_ids']])

    def test_shared_edge_midpoints_tie_the_two_owners(self):
        a=build(16);source=binding(a);sites=dict(zip(source['site_ids'],np.array(source['site_directions'])))
        edgeids=a.interplate_edges
        f=a.frames(edgeids);q=f.position_m/SPHERE.radius_m
        for j,i in enumerate(edgeids):
            edge=a.edge(i)
            self.assertLess(abs(q[j]@sites[edge.left_plate_id]-q[j]@sites[edge.right_plate_id]),ATOL)
        self.assertEqual(owners(a,q),[{a.edge(i).left_plate_id,a.edge(i).right_plate_id} for i in edgeids])

    def test_generated_junctions_have_three_owners(self):
        a=build(16)
        self.assertTrue(all(len(v)==3 for v in owners(a,a.vertex_directions)))

    def test_scipy_area_comparison(self):
        from scipy.spatial import SphericalVoronoi
        a=build(24);s=np.array(binding(a)['site_directions'])
        v=SphericalVoronoi(s);v.sort_vertices_of_regions()
        assert_allclose(list(a.areas().values()),4*v.calculate_areas(),atol=ATOL,rtol=RTOL)

    def test_radius_scales_areas_and_perimeters_only(self):
        p=prepare(SPHERE,TETRA).build();q=prepare(SphericalFrame(6.,SPHERE.frame_id),TETRA).build()
        assert_allclose(list(q.areas().values()),np.array(list(p.areas().values()))*9,rtol=RTOL,atol=ATOL)
        assert_allclose(list(q.perimeters().values()),np.array(list(p.perimeters().values()))*3,rtol=RTOL,atol=ATOL)
        self.assertEqual(owners(p,directions()),owners(q,directions()))

    def test_rotation_covariance(self):
        p=prepare(SPHERE,TETRA).build();r=Rotation.from_axis_angle([2,4,1],.7)
        sites=dict(zip(sorted(TETRA),r.apply(np.array([TETRA[k] for k in sorted(TETRA)]))))
        q=prepare(SPHERE,sites).build()
        self.assertEqual(owners(p,directions()),owners(q,r.apply(directions())))
        assert_allclose(list(p.areas().values()),list(q.areas().values()),rtol=RTOL,atol=ATOL)

    def test_poles_and_longitude_seam_not_special_boundaries(self):
        a=build();pts=np.array([[0,0,1],[0,0,-1],[-1,1e-8,0],[-1,-1e-8,0]])
        sites=np.array(binding(a)['site_directions']);names=binding(a)['site_ids']
        self.assertEqual(owners(a,pts),[{names[i]} for i in np.argmax(pts@sites.T,axis=1)])


class ReproducibilityAndPatches(unittest.TestCase):
    def test_same_seed_same_atlas_bytes(self):
        a=build();b=build()
        self.assertEqual(a.descriptor(),b.descriptor());self.assertEqual(a._points,b._points)

    def test_different_seeds_change_geometry(self):
        self.assertNotEqual(build(seed=1).geometry_id,build(seed=2).geometry_id)

    def test_global_rng_unchanged_and_not_used(self):
        before=np.random.get_state();a=build()
        after=np.random.get_state()
        self.assertEqual(before[0],after[0]);assert_array_equal(before[1],after[1]);self.assertEqual(before[2:],after[2:])
        np.random.seed(27)
        try:self.assertEqual(a.geometry_id,build().geometry_id)
        finally:np.random.set_state(before)

    def test_names_and_directions_independent_of_mapping_order(self):
        a=prepare(SPHERE,TETRA);b=prepare(SPHERE,dict(reversed(list(TETRA.items()))))
        self.assertEqual(a.partition_id,b.partition_id);self.assertEqual(a.build().atlas_id,b.build().atlas_id)

    def test_prepared_plan_reuses_hull(self):
        p=prepare(SPHERE,TETRA)
        with mock.patch('scipy.spatial.ConvexHull',side_effect=AssertionError('rebuilt hull')):
            a=p.build();b=p.build(patch_layout='triangles')
        self.assertEqual(generated_partition_id(a),generated_partition_id(b))

    def test_fan_layout_preserves_geography(self):
        a=build();b=repatch(a)
        self.assertNotEqual(a.atlas_id,b.atlas_id)
        self.assertEqual(generated_partition_id(a),generated_partition_id(b))
        self.assertEqual(a.adjacency(),b.adjacency())
        assert_allclose(list(a.areas().values()),list(b.areas().values()),rtol=RTOL,atol=ATOL)
        assert_allclose(list(a.perimeters().values()),list(b.perimeters().values()),rtol=RTOL,atol=ATOL)
        self.assertEqual(owners(a,directions()),owners(b,directions()))

    def test_physical_edge_identities_survive_layout(self):
        a=build();b=repatch(a)
        self.assertEqual({a.edge_ids[i] for i in a.interplate_edges},{b.edge_ids[i] for i in b.interplate_edges})
        self.assertGreater(len(b.patches),len(a.patches))
        self.assertGreater(sum(b.role(i)=='patch-seam' for i in range(b.edge_count)),0)

    def test_small_count_layouts_preserve_ownership(self):
        for n in (1,2,3):
            a=build(n);b=repatch(a)
            self.assertEqual(generated_partition_id(a),generated_partition_id(b))
            self.assertEqual(owners(a,directions(50)),owners(b,directions(50)))
            assert_allclose(list(a.areas().values()),list(b.areas().values()),atol=ATOL,rtol=RTOL)

    def test_generate_layout_choice_does_not_change_sites(self):
        s=PlanetPartitionSettings(12,42)
        a=generate(SPHERE,s);b=generate(SPHERE,replace(s,patch_layout='triangles'))
        self.assertEqual(binding(a)['site_directions'],binding(b)['site_directions'])
        self.assertEqual(generated_partition_id(a),generated_partition_id(b))

    def test_repatch_does_not_call_random_generator(self):
        a=build()
        with mock.patch('atlas_tectonics.planetary_generation._draw_sites',side_effect=AssertionError('rerolled')):
            b=repatch(a)
        self.assertEqual(generated_partition_id(a),generated_partition_id(b))

    def test_batch_limit_does_not_change_geometry(self):
        a=build(limits=GeometryLimits(batch_points=3));b=build(limits=GeometryLimits(batch_points=100))
        self.assertEqual(a.atlas_id,b.atlas_id)

    def test_workers_do_not_change_seed_mapping(self):
        with ThreadPoolExecutor(3) as pool:out=list(pool.map(lambda n:build(n,72),(12,8,12,8)))
        self.assertEqual(out[0].atlas_id,out[2].atlas_id);self.assertEqual(out[1].atlas_id,out[3].atlas_id)

    def test_candidate_prefix_draw_mapping(self):
        self.assertEqual(_draw_sites(7,8,0).tobytes(),_draw_sites(7,12,0)[:8].tobytes())
        self.assertNotEqual(_draw_sites(7,8,0).tobytes(),_draw_sites(7,8,1).tobytes())

    def test_rejections_are_bounded_and_recorded(self):
        a=build(4,42);g=binding(a)['generation']
        self.assertGreater(g['accepted_attempt'],0)
        self.assertEqual(sum(g['rejections'].values()),g['accepted_attempt'])
        with self.assertRaises(PartitionGenerationError) as caught:
            generate(SPHERE,PlanetPartitionSettings(4,42,max_attempts=1))
        self.assertEqual(caught.exception.attempts,1)

    def test_authored_sites_are_not_resampled(self):
        bad={str(i):[.1*i,.02*i*i,1.] for i in range(4)}
        with mock.patch('atlas_tectonics.planetary_generation._draw_sites',side_effect=AssertionError('rerolled')):
            with self.assertRaises(PartitionCandidateError):prepare(SPHERE,bad)

    def test_final_validator_error_not_hidden_by_retry(self):
        with mock.patch('atlas_tectonics.planetary_generation.build_spherical_atlas',side_effect=GeometryError('audit failure')) as spy:
            with self.assertRaisesRegex(GeometryError,'audit failure'):build()
        self.assertEqual(spy.call_count,1)

    def test_source_contains_selected_prior_and_runtime(self):
        source=binding(build())
        self.assertFalse(source['physical_validation'])
        self.assertIn('conditioned',source['prior'])
        self.assertEqual(source['runtime']['qhull_options'],'Qc; Qt implicit; no QJ')
        self.assertEqual(len(source['runtime']['qhull_binary_sha256']),64)


class InvalidInputsAndResources(unittest.TestCase):
    def test_settings_reject_invalid_counts(self):
        for n in (True,0,-1,1.5,'8'):
            with self.subTest(n=n),self.assertRaises(GeometryError):PlanetPartitionSettings(n,42)

    def test_settings_reject_invalid_seeds(self):
        for seed in (True,-1,2**128,1.5,'42'):
            with self.subTest(seed=seed),self.assertRaises(GeometryError):PlanetPartitionSettings(4,seed)

    def test_settings_reject_invalid_attempts(self):
        for count in (True,0,-1,4097,1.5):
            with self.subTest(count=count),self.assertRaises(GeometryError):PlanetPartitionSettings(4,42,count)

    def test_settings_immutable(self):
        with self.assertRaises(FrozenInstanceError):PlanetPartitionSettings(8,42).seed=4

    def test_invalid_layout_refused(self):
        with self.assertRaises(GeometryError):PlanetPartitionSettings(8,42,patch_layout='snap')
        with self.assertRaises(GeometryError):prepare(SPHERE,TETRA).build(patch_layout=None)

    def test_explicit_sphere_and_settings_required(self):
        for args in ((None,PlanetPartitionSettings(4,42)),(SPHERE,{})):
            with self.assertRaises(GeometryError):generate(*args)

    def test_sites_invalid_shape_types_masks_nonfinite(self):
        for value in ((1,2),[True,1.,0.],[np.nan,1.,0.],[np.inf,1.,0.],np.ma.array([1.,0,0]),[0.,0.,0.]):
            with self.subTest(value=str(value)),self.assertRaises(GeometryError if np.shape(value)!=(3,) else ValueError):
                prepare(SPHERE,{'x':value})

    def test_invalid_site_inventory(self):
        for sites in ({},{'':(1,0,0)},[(1,0,0)]):
            with self.assertRaises(ValueError):prepare(SPHERE,sites)

    def test_duplicate_and_nearly_duplicate_sites_refused(self):
        for delta in (0.,1e-12):
            with self.assertRaises(PartitionCandidateError):prepare(SPHERE,{'a':(1,0,0),'b':(1,delta,0)})

    def test_degenerate_cofacets_not_jittered(self):
        from itertools import product
        sites={str(i):v for i,v in enumerate(product((-1.,1.),repeat=3))}
        with self.assertRaisesRegex(PartitionCandidateError,'cofacets'):prepare(SPHERE,sites)

    def test_coplanar_four_sites_refused(self):
        with self.assertRaises(PartitionCandidateError):prepare(SPHERE,{'a':(1,0,0),'b':(0,1,0),'c':(-1,0,0),'d':(0,-1,0)})

    def test_nonspanning_sites_refused(self):
        with self.assertRaises(PartitionCandidateError):prepare(SPHERE,{'a':(1,0,2),'b':(0,1,2),'c':(-1,0,2),'d':(0,-1,3)})

    def test_geometry_limit_before_rng_or_native_allocation(self):
        with mock.patch('atlas_tectonics.planetary_generation._draw_sites',side_effect=AssertionError('allocated')):
            with self.assertRaises(GeometryError):build(10000,limits=GeometryLimits(max_vertices=100))

    def test_budget_before_random_allocation(self):
        b=WorkBudget(100)
        with mock.patch('atlas_tectonics.planetary_generation._draw_sites',side_effect=AssertionError('allocated')):
            with self.assertRaises(MemoryLimitError):build(budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_budget_failure_not_retried(self):
        b=WorkBudget(100000)
        with mock.patch('atlas_tectonics.planetary_generation._draw_sites',wraps=_draw_sites) as spy:
            with self.assertRaises(MemoryLimitError):build(budget=b)
        self.assertEqual(spy.call_count,1);self.assertEqual(b.reserved_bytes,0)

    def test_cancellation_before_sampling(self):
        c=threading.Event();c.set()
        with mock.patch('atlas_tectonics.planetary_generation._draw_sites',side_effect=AssertionError('sampled')):
            with self.assertRaises(CancelledError):build(cancel=c)

    def test_cancellation_between_candidate_and_topology(self):
        c=threading.Event();b=WorkBudget(8<<20)
        def stop(*a):c.set();return _draw_sites(*a)
        with mock.patch('atlas_tectonics.planetary_generation._draw_sites',side_effect=stop):
            with self.assertRaises(CancelledError):build(cancel=c,budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_plan_build_cancel_and_budget_release(self):
        p=prepare(SPHERE,TETRA);b=WorkBudget(128<<20)
        c=threading.Event();c.set()
        with self.assertRaises(CancelledError):p.build(cancel=c,budget=b)
        self.assertEqual(b.reserved_bytes,0)
        p.build(budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_no_global_array_pair_matrix(self):
        a=build(96)
        self.assertFalse(a.statistics['global_dense_pair_matrix'])
        self.assertEqual(a.vertex_count,2*96-4)
        self.assertEqual(a.edge_count,3*96-6)

    def test_native_hull_called_once_per_preparation(self):
        from scipy.spatial import ConvexHull
        with mock.patch('scipy.spatial.ConvexHull',wraps=ConvexHull) as spy:prepare(SPHERE,TETRA)
        self.assertEqual(spy.call_count,1)


class ImmutabilityAndPersistence(unittest.TestCase):
    def test_plan_detaches_mutable_sites(self):
        inputs={k:np.array(v,dtype=float) for k,v in TETRA.items()};p=prepare(SPHERE,inputs);old=p.partition_id
        for v in inputs.values():v[:]=0
        self.assertEqual(p.partition_id,old);p.build()
        with self.assertRaises(ValueError):p.site_directions.setflags(write=True)
        with self.assertRaises(ValueError):p.vertex_directions.setflags(write=True)

    def test_returned_array_metadata_cannot_change_plan(self):
        p=prepare(SPHERE,TETRA);a=p.site_directions;a.shape=(12,)
        self.assertEqual(p.site_directions.shape,(4,3))

    def test_prepared_plan_pickle_rebuild(self):
        p=prepare(SPHERE,TETRA);restored=pickle.loads(pickle.dumps(p))
        self.assertEqual(p.partition_id,restored.partition_id)
        self.assertEqual(p.build().geometry_id,restored.build().geometry_id)
        with self.assertRaises(ValueError):restored.site_directions.setflags(write=True)

    def test_plan_deepcopy_shares_immutable_definition(self):
        p=prepare(SPHERE,TETRA);self.assertIs(copy.deepcopy(p),p)

    def test_plan_restore_refuses_changed_bytes(self):
        p=prepare(SPHERE,TETRA)
        with self.assertRaises(GeometryError):_restore_plan(p.sphere,p.plate_ids,b'bad',p.partition_id)
        with self.assertRaises(GeometryError):_restore_plan(p.sphere,p.plate_ids,p._sites,'0'*64)

    def test_concurrent_repatch_of_one_plan(self):
        p=prepare(SPHERE,TETRA)
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:p.build(),range(4)))
        self.assertEqual(len({a.atlas_id for a in results}),1)

    def test_full_atlas_pickle_and_immutable_restore(self):
        a=build();b=pickle.loads(pickle.dumps(a))
        self.assertEqual(a.atlas_id,b.atlas_id)
        with self.assertRaises(ValueError):b.vertex_directions.setflags(write=True)

    def test_compressed_snapshot_retains_generation_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'a.db',StoreLimits(4096,4<<20,16<<20)) as s:
            a=build();save(a,s);first=s.statistics()['unique_chunks'];save(a,s)
            self.assertEqual(s.statistics()['unique_chunks'],first)
            b=load(s,a.atlas_id);self.assertEqual(a.descriptor(),b.descriptor())
            self.assertEqual(owners(a,directions(16)),owners(b,directions(16)))
            c=repatch(b);self.assertEqual(generated_partition_id(c),generated_partition_id(a))

    def test_corrupted_snapshot_refused_not_regenerated(self):
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'a.db',StoreLimits(4096,4<<20,16<<20)) as s:
            a=build();save(a,s)
            other=sqlite3.connect(s.path);other.execute("UPDATE chunks SET payload=?",(b'bad',));other.commit();other.close()
            with self.assertRaises(StoreError):load(s,a.atlas_id)

    def test_backup_restores_after_original_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a.db';dest=Path(tmp)/'b.db';lim=StoreLimits(4096,4<<20,16<<20)
            with ArrayStore(path,lim) as s:a=build();save(a,s);s.backup_to(dest)
            path.unlink()
            with ArrayStore(dest,lim) as s:self.assertEqual(load(s,a.atlas_id).atlas_id,a.atlas_id)

    def test_fresh_process_seed_reproducibility(self):
        a=build()
        code="""from atlas_tectonics import *
a=generate_planetary_partition(SphericalFrame(2.,'synthetic-planet'),PlanetPartitionSettings(12,72))
print(a.atlas_id)
"""
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
        proc=subprocess.run([sys.executable,'-B','-c',code],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(proc.stdout.strip(),a.atlas_id)

    def test_fresh_process_snapshot_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a.db';lim=StoreLimits(4096,4<<20,16<<20)
            with ArrayStore(path,lim) as s:a=build();save(a,s)
            code="""import sys
from atlas_tectonics import *
from atlas_tectonics.storage import *
with ArrayStore(sys.argv[1],StoreLimits(4096,4<<20,16<<20)) as s:
 a=load_spherical_atlas(s,sys.argv[2]); print(a.atlas_id)
"""
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
            proc=subprocess.run([sys.executable,'-B','-c',code,str(path),a.atlas_id],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(proc.stdout.strip(),a.atlas_id)

    def test_execution_identity_covers_generator_and_qhull(self):
        import atlas_tectonics.planetary_generation as g
        with ExecutionContext() as ctx:
            ctx.verify()
            with mock.patch.object(g,'_SPAN_MARGIN',2e-10):
                with self.assertRaises(ValueError):ctx.verify()

    def test_reference_only_does_not_eagerly_import_spatial_runtime(self):
        # Import is light; dependency errors belong to requested geometry operations.
        code="""import sys
import atlas_tectonics
print('scipy.spatial._qhull' in sys.modules)
"""
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
        proc=subprocess.run([sys.executable,'-B','-c',code],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(proc.stdout.strip(),'False')


if __name__=='__main__':unittest.main()
