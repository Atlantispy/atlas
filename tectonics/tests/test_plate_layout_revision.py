"""Stage-3C correction: sourced calibration, independent geometry and kinematics.

No test says an area fit certifies realistic tectonics. Cocos shape and AF/AN
motion are withheld from generation. Older fixtures/tolerances remain untouched.
Only bounded synthetic arrays and temporary local stores; no network or install.
"""
from concurrent.futures import CancelledError
from dataclasses import replace, FrozenInstanceError
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_allclose
from atlas_tectonics import (SphericalFrame, Rotation, GeometryError, GeometryLimits,
    PlanetPartitionSettings, generate_planetary_partition, PlateLayoutSettings,
    generate_plate_layout, layout_metrics, plate_outline_cycles,
    evaluate_plate_kinematics, require_geological_layout_acceptance,
    save_spherical_atlas, load_spherical_atlas)
from atlas_tectonics.plate_reference import (AREA_ROWS, COCOS_COORDINATES, STEP_ROWS,
    plate_reference_record, outline_reference_record, reference_area_fractions,
    reference_motion_sample, spherical_ring_metrics, lonlat_directions)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
from atlas_tectonics.reuse import ExecutionContext

SPHERE=SphericalFrame(2.,'synthetic-reference-revision')
ATOL=2e-12  # Existing W01 geometric angular/relative comparison level.

class ReferenceTests(unittest.TestCase):
    def test_52_unique_published_areas(self):
        self.assertEqual(len(AREA_ROWS),52);self.assertEqual(len(dict(AREA_ROWS)),52)
        self.assertTrue(all(a>0 for _,a in AREA_ROWS))
        # Table precision: each printed value rounded to 0.00001 sr.
        self.assertLess(abs(math.fsum(v for _,v in AREA_ROWS)-4*math.pi),52*.000005)
    def test_independent_area_anchors(self):
        d=dict(AREA_ROWS)
        self.assertEqual(d['PA'],2.57685);self.assertEqual(d['AF'],1.44065)
        self.assertEqual(d['MN'],.00020);self.assertEqual(d['CO'],.07223)
    def test_rank_prior_is_declared_normalisation(self):
        p=reference_area_fractions(12);self.assertAlmostEqual(math.fsum(p),1.)
        expected=sorted([a for _,a in AREA_ROWS],reverse=True)[:12]
        assert_allclose(p,np.array(expected)/math.fsum(expected),rtol=0,atol=1e-16)
        with self.assertRaises(ValueError):p.setflags(write=True)
    def test_count_is_explicit_not_universal(self):
        for n in (True,1,53,12.0,'12'):
            with self.subTest(n=n),self.assertRaises(GeometryError):reference_area_fractions(n)
    def test_reference_records_are_detached_and_identified(self):
        a=plate_reference_record();b=plate_reference_record()
        self.assertEqual(a['reference_sha256'],b['reference_sha256'])
        a['areas']['PA']=0;self.assertEqual(plate_reference_record()['areas']['PA'],2.57685)
        self.assertIn('single present-day reconstruction',b['limitations'])
    def test_published_motion_sample(self):
        a=reference_motion_sample()
        # 0.001-degree step positions and 0.1 mm/a tabulation are rounded;
        # 0.2 mm/a is a conservative source-resolution allowance, NOT a solver
        # tolerance. No source values or kernel constants are fitted to this test.
        self.assertEqual(a.shape,(12,4));self.assertLess(np.max(abs(a[:,:2]-a[:,2:])),.2)
        self.assertGreater(a[2,0],13.);self.assertLess(a[3,0],0.)
    def test_reference_velocity_units_scale_with_radius(self):
        a=reference_motion_sample();b=reference_motion_sample(2*6371000.)
        assert_allclose(b[:,:2],2*a[:,:2],rtol=2e-15);assert_allclose(b[:,2:],a[:,2:],rtol=0,atol=0)
    def test_source_cocos_is_complete_closed_outline(self):
        self.assertEqual(len(COCOS_COORDINATES),158)
        self.assertEqual(COCOS_COORDINATES[0],COCOS_COORDINATES[-1])
        r=outline_reference_record();self.assertIn('not used to fit',r['role'])
        self.assertEqual(r['source_blob'],'879951b5d17c0e11926025223378174fcb9f41f6')
    def test_cocos_area_agrees_with_independent_printed_table(self):
        r=spherical_ring_metrics(lonlat_directions(COCOS_COORDINATES))
        self.assertLess(abs(r['area_steradians']-.07223),.000005)
        self.assertGreater(r['reflex_turning_radians'],1.)
        self.assertEqual(r['segments'],157)
    def test_cocos_orientation_and_gauss_bonnet(self):
        p=lonlat_directions(COCOS_COORDINATES);a=spherical_ring_metrics(p);b=spherical_ring_metrics(p[::-1])
        self.assertEqual(a['orientation'],-b['orientation'])
        for key in ('area_steradians','perimeter_radians','compactness','reflex_turning_radians'):
            self.assertAlmostEqual(a[key],b[key],delta=ATOL)
        self.assertAlmostEqual(a['signed_turning_radians'],2*math.pi-a['area_steradians'],delta=ATOL)
    def test_octant_independent_area_and_perimeter(self):
        m=spherical_ring_metrics(np.eye(3))
        self.assertAlmostEqual(m['area_steradians'],math.pi/2,delta=ATOL)
        self.assertAlmostEqual(m['perimeter_radians'],3*math.pi/2,delta=ATOL)
        self.assertAlmostEqual(m['reflex_turning_radians'],0,delta=ATOL)
    def test_arc_densification_is_not_added_roughness(self):
        p=lonlat_directions(COCOS_COORDINATES)[:-1];q=np.roll(p,-1,axis=0)
        midpoint=p+q;midpoint/=np.linalg.norm(midpoint,axis=1)[:,None]
        dense=np.stack((p,midpoint),axis=1).reshape(-1,3)
        a=spherical_ring_metrics(p);b=spherical_ring_metrics(dense)
        for k in ('area_steradians','perimeter_radians','reflex_turning_radians'):
            self.assertAlmostEqual(a[k],b[k],delta=5e-12)
    def test_rotating_source_outline_preserves_measurements(self):
        p=lonlat_directions(COCOS_COORDINATES)
        q=Rotation.from_axis_angle([1,2,3],.8).apply(p)
        a=spherical_ring_metrics(p);b=spherical_ring_metrics(q)
        for k in ('area_steradians','perimeter_radians','compactness','reflex_turning_radians'):
            self.assertAlmostEqual(a[k],b[k],delta=5e-12)
    def test_invalid_outline_types_and_crossing_refused(self):
        bad=(np.zeros((3,3)),np.ma.array(np.eye(3)),np.eye(3)[:2],[[1,0,float('nan')]]*3,
             lonlat_directions([[0,0],[1,1],[0,1],[1,0]]))
        for x in bad:
            with self.subTest(x=str(x)),self.assertRaises((GeometryError,ValueError)):spherical_ring_metrics(x)
    def test_outline_memory_and_cancellation(self):
        with self.assertRaises(MemoryLimitError):spherical_ring_metrics(np.eye(3),budget=WorkBudget(10))
        cancel=threading.Event();cancel.set()
        with self.assertRaises(CancelledError):spherical_ring_metrics(np.eye(3),cancel=cancel)
    def test_direction_scale_is_not_radius(self):
        assert_allclose(spherical_ring_metrics(np.eye(3)*1e300)['area_steradians'],math.pi/2,atol=ATOL)

class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings=PlateLayoutSettings(6,41,96)
        cls.atlas=generate_plate_layout(SPHERE,cls.settings)
    def test_complete_coverage_and_requested_population(self):
        a=self.atlas
        self.assertEqual(len(a.plate_ids),6)
        self.assertAlmostEqual(math.fsum(a.patch_areas_sr),4*math.pi,delta=2e-11)
        self.assertEqual(a.vertex_count-a.edge_count+len(a.patches),2)
    def test_independent_owner_connectivity(self):
        a=self.atlas;owners=[p.plate_id for p in a.patches]
        adjacent=[set() for _ in owners]
        for l,r in a.side_patches:adjacent[l].add(int(r));adjacent[r].add(int(l))
        for plate in a.plate_ids:
            wanted={i for i,p in enumerate(owners) if p==plate};stack=[min(wanted)];seen=set()
            while stack:
                i=stack.pop()
                if i in seen:continue
                seen.add(i);stack.extend((adjacent[i]&wanted)-seen)
            self.assertEqual(seen,wanted)
    def test_ranked_fit_is_calibration_not_validation(self):
        binding=self.atlas.descriptor()['source_bindings']['plate_layout']
        self.assertLessEqual(binding['area_l1_error'],self.settings.max_area_l1_error)
        self.assertFalse(binding['acceptance']['geological_validation'])
        self.assertEqual(binding['acceptance']['outline_morphology'],'NOT_ACCEPTED')
        self.assertEqual(binding['reference']['areas']['CO'],.07223)
    def test_statistical_candidate_removes_single_site_per_plate(self):
        self.assertGreater(len(self.atlas.patches),len(self.atlas.plate_ids)*4)
        self.assertEqual(layout_metrics(self.atlas)['connected_components'],[1]*6)
        reflex=[]
        # This separate outline diagnostic is explicitly hemisphere-bounded.
        # The global atlas can still represent larger plate outlines.
        for p in self.atlas.plate_ids[1:]:
            for ring in plate_outline_cycles(self.atlas,p):reflex.append(spherical_ring_metrics(ring)['reflex_turning_radians'])
        self.assertGreater(max(reflex),1.)
    def test_old_fixture_retains_its_exact_semantics(self):
        a=generate_planetary_partition(SPHERE,PlanetPartitionSettings(6,41))
        self.assertIn('partition_generation',a.descriptor()['source_bindings'])
        old=np.array(layout_metrics(a)['ranked_area_fractions'])
        new=np.sort(layout_metrics(self.atlas)['area_fractions'])[::-1]
        target=reference_area_fractions(6)
        self.assertLess(abs(new-target).sum(),abs(old-target).sum())
    def test_seed_reproducibility_independent_of_global_rng(self):
        np.random.seed(512);np.random.random(100)
        a=generate_plate_layout(SPHERE,self.settings)
        self.assertEqual(a.atlas_id,self.atlas.atlas_id)
    def test_different_seed_new_world(self):
        a=generate_plate_layout(SPHERE,replace(self.settings,seed=42))
        self.assertNotEqual(a.geometry_id,self.atlas.geometry_id)
    def test_no_quiet_downgrade_on_bad_shape_or_budget(self):
        for args in ((1,0,100),(6,True,100),(6,-1,100),(6,0,5),(6,0,100,.2)):
            with self.subTest(args=args),self.assertRaises((GeometryError,ValueError)):PlateLayoutSettings(*args)
        with self.assertRaises(MemoryLimitError):generate_plate_layout(SPHERE,self.settings,budget=WorkBudget(100))
    def test_small_plate_accuracy_not_hidden_by_global_l1(self):
        with self.assertRaisesRegex(GeometryError,'small plate|unresolved'):
            generate_plate_layout(SPHERE,PlateLayoutSettings(52,41,256))
    def test_unresolved_accuracy_refuses_without_retrying_relaxed_tolerance(self):
        with self.assertRaises(GeometryError):generate_plate_layout(SPHERE,replace(self.settings,max_area_l1_error=1e-10))
    def test_cancelled_before_generation(self):
        event=threading.Event();event.set()
        with self.assertRaises(CancelledError):generate_plate_layout(SPHERE,self.settings,cancel=event)
    def test_geometry_limit_preserved(self):
        with self.assertRaises(GeometryError):generate_plate_layout(SPHERE,self.settings,limits=GeometryLimits(max_vertices=8))
    def test_case_records_cannot_grant_scientific_acceptance(self):
        desc=self.atlas.descriptor();desc['source_bindings']['plate_layout']['acceptance']['geological_validation']=True
        with self.assertRaisesRegex(GeometryError,'remains open'):require_geological_layout_acceptance(self.atlas)
    def test_returned_geometry_and_rings_immutable(self):
        with self.assertRaises(ValueError):self.atlas.vertex_directions.setflags(write=True)
        for r in plate_outline_cycles(self.atlas,self.atlas.plate_ids[0]):
            with self.assertRaises(ValueError):r.setflags(write=True)
    def test_plain_common_rotation_no_relative_motion(self):
        r=evaluate_plate_kinematics(self.atlas,{p:[.1,.2,.3] for p in self.atlas.plate_ids})
        assert_allclose(r['values'],0,rtol=0,atol=0)
        self.assertLess(max(abs(x) for x in r['own_area_rate_sr_s'].values()),ATOL)
    def test_rigid_closed_area_integral_and_radial_motion(self):
        r=evaluate_plate_kinematics(self.atlas,{p:[i*.1,.2,-.3] for i,p in enumerate(self.atlas.plate_ids)})
        assert_allclose(r['values'][:,2],0,rtol=0,atol=ATOL)
        self.assertLess(max(abs(x) for x in r['own_area_rate_sr_s'].values()),ATOL)
        with self.assertRaises(ValueError):r['values'].setflags(write=True)
    def test_existing_boundary_motion_agrees_with_euler_diagnostic(self):
        a=self.atlas;omegas={p:np.array([i*.1,.2,-.3]) for i,p in enumerate(a.plate_ids)}
        f=a.frames(a.interplate_edges)
        velocities={p:np.cross(w,f.position_m) for p,w in omegas.items()}
        old=a.motion(velocities,[0,0,0]);new=evaluate_plate_kinematics(a,omegas)
        assert_allclose(old.values_m_s[:,[0,1,4]],new['values'],rtol=ATOL,atol=ATOL)
    def test_missing_extra_and_invalid_poles_refused(self):
        full={p:[0,0,0] for p in self.atlas.plate_ids}
        for m in ({},dict(full,unknown=[0,0,0]),dict(full,**{self.atlas.plate_ids[0]:[float('inf'),0,0]})):
            with self.assertRaises((GeometryError,ValueError)):evaluate_plate_kinematics(self.atlas,m)
    def test_no_inferred_subduction_or_new_motion(self):
        r=evaluate_plate_kinematics(self.atlas,{p:[0,0,0] for p in self.atlas.plate_ids})
        self.assertIn('no polarity',r['interpretation']);self.assertNotIn('subducting_side',r)
    def test_same_payload_snapshot_and_backup_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            limits=StoreLimits(65536,16<<20,64<<20)
            original=Path(tmp)/'a.db';backup=Path(tmp)/'b.db'
            with ArrayStore(original,limits) as s:
                key=save_spherical_atlas(self.atlas,s);count=s.statistics()['unique_chunks']
                save_spherical_atlas(self.atlas,s);self.assertEqual(s.statistics()['unique_chunks'],count)
                s.backup_to(backup)
            original.unlink()
            with ArrayStore(backup,limits) as s:a=load_spherical_atlas(s,key)
            self.assertEqual(a.atlas_id,self.atlas.atlas_id)
            self.assertEqual(a.descriptor()['source_bindings'],self.atlas.descriptor()['source_bindings'])
    def test_existing_execution_context_covers_new_source_and_data(self):
        import atlas_tectonics.plate_reference as ref
        with ExecutionContext() as context:
            context.verify()
            with mock.patch.object(ref,'AREA_ROWS',ref.AREA_ROWS[:-1]):
                with self.assertRaises(ValueError):context.verify()


class AdditionalIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings=PlateLayoutSettings(6,41,96)
        cls.atlas=generate_plate_layout(SPHERE,cls.settings)
    def test_index_preserves_actual_support_ownership(self):
        a=self.atlas;points=np.array([p.chart.centre for p in a.patches])
        with a.index() as index:hit=index.query(points)
        groups=[set() for _ in points]
        for i,j in hit.pairs:groups[int(i)].add(hit.owner_ids[int(j)])
        for expected,actual in zip(a.patches,groups):self.assertEqual(actual,{expected.plate_id})
    def test_stage4_geology_accepts_the_same_atlas_without_relabelling(self):
        from test_w01_geological_description import make
        from atlas_tectonics import save_geological_case,load_geological_case
        case=make(self.atlas)
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'case.db',StoreLimits(65536,16<<20,64<<20)) as store:
            key=save_geological_case(case,store);restored=load_geological_case(store,key)
            self.assertEqual(restored.case_id,case.case_id)
            self.assertEqual(restored.topology.geometry_id,self.atlas.geometry_id)
    def test_reference_shape_is_not_a_generation_input(self):
        import atlas_tectonics.plate_reference as ref
        with mock.patch.object(ref,'COCOS_COORDINATES',((0.,0.),(1.,0.),(0.,1.),(0.,0.))):
            altered=generate_plate_layout(SPHERE,self.settings)
        # Execution provenance changes because source-data constants changed,
        # but no geometric decision is fitted to the withheld outline.
        self.assertEqual(altered.geometry_id,self.atlas.geometry_id)
    def test_cold_process_restores_the_same_reference_conditioned_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'world.db';limits=StoreLimits(65536,16<<20,64<<20)
            with ArrayStore(path,limits) as store:key=save_spherical_atlas(self.atlas,store)
            code="""from atlas_tectonics import load_spherical_atlas
from atlas_tectonics.storage import ArrayStore,StoreLimits
import sys
with ArrayStore(sys.argv[1],StoreLimits(65536,16<<20,64<<20)) as store:
 a=load_spherical_atlas(store,sys.argv[2]);print(a.atlas_id)
"""
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
            p=subprocess.run([sys.executable,'-B','-c',code,str(path),key],env=env,text=True,capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),self.atlas.atlas_id)
    def test_actual_method_source_is_part_of_generation_identity(self):
        record=self.atlas.descriptor()['source_bindings']['plate_layout']
        self.assertEqual(len(record['execution_id']),64)
    def test_kinematic_memory_and_pre_cancel_release(self):
        b=WorkBudget(100);motion={p:[0.,0.,0.] for p in self.atlas.plate_ids}
        with self.assertRaises(MemoryLimitError):evaluate_plate_kinematics(self.atlas,motion,budget=b)
        self.assertEqual(b.reserved_bytes,0)
        c=threading.Event();c.set()
        with self.assertRaises(CancelledError):evaluate_plate_kinematics(self.atlas,motion,cancel=c)

if __name__=='__main__':unittest.main()
