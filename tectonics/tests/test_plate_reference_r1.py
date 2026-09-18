"""3C-R1 numerical/parser contracts, not a fabricated full-PB2002 run.

All existing PB2002 Cocos/AF-AN excerpts are explicitly already exposed. Complete
source verification is a separate command which fails closed if files are absent.
Synthetic geometry validates maths only; it never impersonates an Earth dataset.
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import replace, FrozenInstanceError
from pathlib import Path
from decimal import Decimal
from unittest import mock
import hashlib
import importlib.util
import io
import json
import math
import pickle
import tempfile
import threading
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import Rotation
from atlas_tectonics.plate_reference import COCOS_COORDINATES, POLE_ROWS, STEP_ROWS, reference_motion_sample
from atlas_tectonics.plate_reference_dataset import (
    ReferenceDataError,ReferenceCurve,EulerPole,BoundaryStep,PB2002Dataset,
    PB2002_COMMIT,PB2002_FILES,source_manifest,verify_source_bytes,
    parse_dig,parse_poles,parse_steps,load_pb2002,lonlat_vectors,
    spherical_ring_measures,sample_ring_at_scale,multiscale_ring_measures,step_motion,
)
from atlas_tectonics.plate_reference_acceptance import (
    reference_protocol,record_role,evaluation_record,boundary_inventory,
    reference_dataset_report,write_report_snapshot,read_report_snapshot,
    compare_distributions,_vertex_key,
)
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.storage import ArrayStore,StoreLimits,Compression,StoreError

ROOT=Path(__file__).resolve().parents[1]
ID='a'*64
OTHER='b'*64
LICENCE=b'**This collection of data is made available under the Open Data Commons Attribution License: [http://opendatacommons.org/licenses/by/1.0/](http://opendatacommons.org/licenses/by/1.0/)**\n'
DIG='AA\n 0,0\n 90,0\n 0,90\n 0,0\n*** end of line segment ***\n'


def line_step(number=1,boundary='AF-AN',continuous=False,start=(-.438,-54.852),end=(-.039,-54.677),
              length=32.1,azimuth=53,speed=13.2,vazimuth=48,opening=1.2,lateral=13.1,elevation=-1584,
              age=2,kind='OTF',sameclass=False,orogen=False):
    # Independent fixed-column fixture builder following source Table 2.
    row=[' ']*96
    def place(a,b,v):
        text=str(v).rjust(b-a)
        if len(text)!=b-a:raise ValueError('fixture width')
        row[a:b]=text
    place(0,4,number);row[5]=':' if continuous else ' ';row[6:11]=boundary
    for a,b,v in [(12,20,start[0]),(21,28,start[1]),(29,37,end[0]),(38,45,end[1]),
                  (46,51,length),(52,55,azimuth),(56,61,speed),(62,65,vazimuth),
                  (66,72,opening),(73,79,lateral),(80,86,elevation),(87,90,age)]:place(a,b,v)
    row[91]=':' if sameclass else ' ';row[92:95]=kind;row[95]='*' if orogen else ' '
    return ''.join(row)+'\n'


def fixture_poles():
    return {n:EulerPole(n,lat,lon,rate) for n,lat,lon,rate in POLE_ROWS}


def report_fixture():
    return dict(schema='atlas.plate-reference-report.r1.v1',status='SYNTHETIC_STORAGE_TEST_ONLY',
                geological_model_accepted=False,generated_planet_assessed=False,
                dataset={'dataset_id':ID},protocol=reference_protocol())


class SourceContracts(unittest.TestCase):
    def test_exact_known_license_source_hash(self):
        self.assertEqual(verify_source_bytes('LICENSE.md',LICENCE),hashlib.sha256(LICENCE).hexdigest())
    def test_no_newline_repair(self):
        with self.assertRaises(ReferenceDataError):verify_source_bytes('LICENSE.md',LICENCE.replace(b'\n',b'\r\n'))
    def test_source_tampering_refused(self):
        with self.assertRaises(ReferenceDataError):verify_source_bytes('LICENSE.md',LICENCE.replace(b'data',b'xxxx'))
    def test_unknown_source_refused(self):
        with self.assertRaises(ReferenceDataError):verify_source_bytes('guess.dat',b'')
    def test_source_manifest_is_detached(self):
        a=source_manifest();a['files'].clear();self.assertEqual(len(source_manifest()['files']),8)
    def test_pins_use_commit_not_mutable_branch(self):
        self.assertTrue(all(PB2002_COMMIT in x['url'] for x in source_manifest()['files']))
    def test_missing_dataset_never_passes(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ReferenceDataError):load_pb2002(d)
    def test_incomplete_source_never_used(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'LICENSE.md').write_bytes(LICENCE)
            with self.assertRaises(ReferenceDataError):load_pb2002(d)
    def test_budget_refusal_precedes_source_reads(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(Path,'open',side_effect=AssertionError('read')):
            with self.assertRaises(MemoryLimitError):load_pb2002(d,budget=WorkBudget(1))
    def test_already_cancelled_releases_admission(self):
        b=WorkBudget(64<<20);event=threading.Event();event.set()
        with tempfile.TemporaryDirectory() as d,self.assertRaises(CancelledError):load_pb2002(d,budget=b,cancel=event)
        self.assertEqual(b.reserved_bytes,0)
    def test_linked_source_directory_refused(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'real';a.mkdir();b=Path(d)/'link';b.symlink_to(a,target_is_directory=True)
            with self.assertRaises(ReferenceDataError):load_pb2002(b)


class ParsingContracts(unittest.TestCase):
    def test_author_polygon_format_and_locator(self):
        r=parse_dig(DIG,'plate')[0];self.assertEqual(r.name,'AA');self.assertEqual(r.record_number,1)
        assert_array_equal(r.coordinates,[[0,0],[90,0],[0,90],[0,0]])
    def test_boundary_duplicate_titles_stay_separate(self):
        text='AF-AN attribution one\n0,0\n1,0\n*** end of line segment ***\nAF-AN attribution two\n1,0\n2,0\n*** end of line segment ***\n'
        a,b=parse_dig(text,'boundary');self.assertNotEqual(a.source_id,b.source_id);self.assertNotEqual(a.source_title,b.source_title)
    def test_subduction_polarity_preserved(self):
        for sep,side in [('/','right'),('\\','left'),('-',None)]:
            r=parse_dig(f'AF{sep}AN\n0,0\n1,0\n*** end of line segment ***\n','boundary')[0]
            self.assertEqual(r.subducting_side,side);self.assertEqual(r.owners,('AF','AN'))
    def test_orogen_not_made_into_plate_code(self):
        r=parse_dig(DIG.replace('AA\n','Persia-Tibet-Burma\n'),'orogen')[0]
        self.assertEqual(r.name,'Persia-Tibet-Burma')
    def test_unterminated_file_refused(self):
        with self.assertRaises(ReferenceDataError):parse_dig(DIG.split('***')[0],'plate')
    def test_empty_and_nul_files_refused(self):
        for text in ('','\0', '\n'):
            with self.assertRaises(ReferenceDataError):parse_dig(text,'plate')
    def test_missing_title_refused(self):
        with self.assertRaises(ReferenceDataError):parse_dig(DIG[3:],'plate')
    def test_polygon_must_be_closed(self):
        with self.assertRaises(ReferenceDataError):parse_dig(DIG.replace(' 0,0\n***',' 1,1\n***'),'plate')
    def test_seam_equivalent_closure_permitted(self):
        r=parse_dig(DIG.replace(' 0,0\n***',' 360,0\n***'),'plate')[0];self.assertEqual(r.coordinates[-1,0],360.)
    def test_duplicate_polygon_names_refused(self):
        with self.assertRaises(ReferenceDataError):parse_dig(DIG+DIG,'plate')
    def test_repeated_adjacent_vertex_refused(self):
        with self.assertRaises(ReferenceDataError):parse_dig(DIG.replace(' 90,0',' 0,0'),'plate')
    def test_arrays_and_descriptors_are_immutable(self):
        r=parse_dig(DIG,'plate')[0];a=r.coordinates;a.shape=(8,)
        self.assertEqual(r.coordinates.shape,(4,2))
        with self.assertRaises(ValueError):r.coordinates.setflags(write=True)
    def test_source_latitude_range(self):
        with self.assertRaises(ReferenceDataError):parse_dig(DIG.replace('0,90','0,91'),'plate')
    def test_signed_poles_and_pacific_zero(self):
        p=parse_poles('AF 59.160 -73.174 0.9270 published\nPA 0.0 0.0 0.0 reference frame\n')
        self.assertEqual(p[0].longitude_deg,-73.174);self.assertEqual(p[1].rate_deg_ma,0.)
    def test_duplicate_poles_refused(self):
        with self.assertRaises(ReferenceDataError):parse_poles('AF 0 0 1\nAF 1 2 3\n')
    def test_infinite_pole_refused(self):
        with self.assertRaises(ReferenceDataError):parse_poles('AF 0 0 nan\n')
    def test_exact_source_first_step_fields(self):
        s=parse_steps(line_step())[0]
        self.assertEqual((s.boundary,s.start,s.end,s.opening_mm_a,s.right_lateral_mm_a,s.kind),('AF-AN',(-.438,-54.852),(-.039,-54.677),1.2,13.1,'OTF'))
    def test_unknown_seafloor_age_is_not_number(self):
        self.assertIsNone(parse_steps(line_step(age=999))[0].seafloor_age_ma)
        self.assertEqual(parse_steps(line_step(age=180))[0].seafloor_age_ma,180)
    def test_deformation_flag_and_class(self):
        s=parse_steps(line_step(kind='SUB',opening=-2.,orogen=True))[0]
        self.assertTrue(s.in_orogen);self.assertEqual(s.kind,'SUB');self.assertEqual(s.opening_mm_a,-2)
    def test_continuity_validates_endpoints(self):
        text=line_step()+line_step(number=2,continuous=True,start=(-.039,-54.677),end=(.443,-54.451),sameclass=True)
        self.assertEqual(len(parse_steps(text)),2)
        with self.assertRaises(ReferenceDataError):parse_steps(line_step()+line_step(number=2,continuous=True))
    def test_missing_step_number_refused(self):
        with self.assertRaises(ReferenceDataError):parse_steps(line_step(number=2))
    def test_unrecognized_class_refused(self):
        with self.assertRaises(ReferenceDataError):parse_steps(line_step(kind='XXX'))
    def test_false_class_continuity_refused(self):
        with self.assertRaises(ReferenceDataError):parse_steps(line_step(sameclass=True))
    def test_unknown_format_tail_refused(self):
        with self.assertRaises(ReferenceDataError):parse_steps(line_step().rstrip()+' extraneous\n')


class IndependentGeometry(unittest.TestCase):
    def test_octant_area_and_perimeter(self):
        m=spherical_ring_measures(np.eye(3));self.assertAlmostEqual(m['area_steradians'],math.pi/2,places=13)
        self.assertAlmostEqual(m['perimeter_radians'],3*math.pi/2,places=13)
    def test_reversal_is_complement_not_automatic_repair(self):
        m=spherical_ring_measures(np.eye(3)[::-1]);self.assertAlmostEqual(m['area_steradians'],7*math.pi/2,places=13)
    def test_global_nonhemisphere_boundary(self):
        p=lonlat_vectors([[0,-30],[90,-30],[180,-30],[270,-30],[0,-30]])
        m=spherical_ring_measures(p)
        self.assertGreater(m['area_steradians'],2*math.pi)
        self.assertLess(m['area_formula_disagreement_sr'],2e-12)
    def test_real_cocos_area_independent_of_old_formula(self):
        p=lonlat_vectors(COCOS_COORDINATES)[::-1]  # Explicit curator-CW to author-CCW observation convention.
        m=spherical_ring_measures(p)
        self.assertLess(abs(m['area_steradians']-.07223),.000005)
        self.assertLess(m['area_formula_disagreement_sr'],2e-12)
    def test_representational_vertex_densification_invariant(self):
        p=np.eye(3);dense=[]
        for a,b in zip(p,np.roll(p,-1,axis=0)):
            for t in np.arange(8)/8:dense.append(a*math.cos(t*math.pi/2)+b*math.sin(t*math.pi/2))
        a=spherical_ring_measures(p);b=spherical_ring_measures(dense)
        for key in ('area_steradians','perimeter_radians','compactness','absolute_turning_radians'):
            self.assertAlmostEqual(a[key],b[key],places=12)
    def test_multiscale_independent_of_collinear_vertices(self):
        p=np.eye(3);dense=[]
        for a,b in zip(p,np.roll(p,-1,axis=0)):
            dense.extend([a,(a+b)/math.sqrt(2)])
        a=sample_ring_at_scale(p,.1);b=sample_ring_at_scale(dense,.1)
        assert_allclose(a,b,rtol=0,atol=2e-14)
    def test_rotation_invariant_metrics(self):
        p=lonlat_vectors(COCOS_COORDINATES)[::-1]
        r=Rotation.from_axis_angle([1,2,3],1.32)
        a=spherical_ring_measures(p);b=spherical_ring_measures(r.apply(p))
        for key in ('area_steradians','perimeter_radians','compactness','absolute_turning_radians','reflex_turning_radians'):
            assert_allclose(a[key],b[key],rtol=2e-12,atol=2e-12)
    def test_polar_longitude_is_not_vertex_displacement(self):
        a=lonlat_vectors([[0,0],[90,0],[0,90]])
        b=lonlat_vectors([[0,0],[90,0],[123,90]])
        self.assertAlmostEqual(spherical_ring_measures(a)['area_steradians'],spherical_ring_measures(b)['area_steradians'])
    def test_longitude_wrap_invariance(self):
        p=np.array(COCOS_COORDINATES);a=lonlat_vectors(p);p[:,0]+=360;b=lonlat_vectors(p)
        assert_allclose(a,b,rtol=0,atol=2e-14)
    def test_short_ring_marked_unresolved_at_scale(self):
        p=lonlat_vectors([[0,0],[.01,0],[0,.01]])
        self.assertIsNone(sample_ring_at_scale(p,1.))
    def test_sample_limit_refuses_instead_of_coarsening(self):
        with self.assertRaises(ReferenceDataError):sample_ring_at_scale(np.eye(3),.00001,max_samples=100)
    def test_sample_ownership(self):
        p=sample_ring_at_scale(np.eye(3),.1)
        with self.assertRaises(ValueError):p.setflags(write=True)
    def test_incompatible_phase_refused(self):
        with self.assertRaises(ReferenceDataError):sample_ring_at_scale(np.eye(3),.1,phase=1)
    def test_sampling_budget_refused_before_allocation(self):
        b=WorkBudget(1)
        with mock.patch('atlas_tectonics.plate_reference_dataset._unit_vectors',side_effect=AssertionError('allocated')):
            with self.assertRaises(MemoryLimitError):sample_ring_at_scale(np.eye(3),.1,budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_area_budget_released(self):
        b=WorkBudget(1<<20);spherical_ring_measures(np.eye(3),budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_cancelled_metrics_refused(self):
        e=threading.Event();e.set()
        with self.assertRaises(CancelledError):spherical_ring_measures(np.eye(3),cancel=e)
    def test_nonfinite_or_masked_geometry_refused(self):
        for p in (np.full((3,3),np.nan),np.ma.array(np.eye(3)),np.zeros((3,3))):
            with self.assertRaises(ValueError):spherical_ring_measures(p)
    def test_antipodal_edge_refused(self):
        with self.assertRaises(ReferenceDataError):spherical_ring_measures([[1,0,0],[-1,0,0],[0,0,1]])
    def test_two_scales_and_phases_explicit(self):
        r=multiscale_ring_measures(np.eye(3),1000.,(100.,200.))
        self.assertEqual(len(r['scales']),2);self.assertEqual([p['phase'] for p in r['scales'][0]['phases']],[0.,.5])
    def test_exact_vertex_key_no_snapping(self):
        self.assertEqual(_vertex_key([180,2]),_vertex_key([-180,2]))
        self.assertNotEqual(_vertex_key([0,2]),_vertex_key([1e-10,2]))
    def test_pole_key_ignores_singular_longitude_only(self):
        self.assertEqual(_vertex_key([0,90]),_vertex_key([100,90]))
        self.assertNotEqual(_vertex_key([0,89.99]),_vertex_key([100,89.99]))


class IndependentMotion(unittest.TestCase):
    def test_published_first_step(self):
        r=step_motion(parse_steps(line_step())[0],fixture_poles())
        self.assertLess(abs(r['opening_error_mm_a']),.2);self.assertLess(abs(r['right_lateral_error_mm_a']),.2)
    def test_existing_12_sample_values_match_reconstruction(self):
        old=reference_motion_sample();poles=fixture_poles()
        for i,row in enumerate(STEP_ROWS):
            base=parse_steps(line_step())[0]
            step=replace(base,number=i+1,start=tuple(row[:2]),end=tuple(row[2:4]),opening_mm_a=row[4],right_lateral_mm_a=row[5])
            r=step_motion(step,poles)
            assert_allclose([r['opening_mm_a'],r['right_lateral_mm_a']],old[i,:2],rtol=1e-11,atol=1e-11)
    def test_trace_and_owner_reversal_preserves_components(self):
        step=parse_steps(line_step())[0]
        reverse=replace(step,boundary='AN-AF',start=step.end,end=step.start)
        a=step_motion(step,fixture_poles());b=step_motion(reverse,fixture_poles())
        assert_allclose([a['opening_mm_a'],a['right_lateral_mm_a']],[b['opening_mm_a'],b['right_lateral_mm_a']],atol=1e-12)
    def test_equal_poles_have_zero_relative_motion(self):
        p={'AF':EulerPole('AF',20,30,1),'AN':EulerPole('AN',20,30,1)}
        a=step_motion(parse_steps(line_step())[0],p)
        self.assertEqual(a['opening_mm_a'],0);self.assertEqual(a['right_lateral_mm_a'],0)
    def test_known_radians_to_mm_year(self):
        p={'AF':EulerPole('AF',90,0,0),'AN':EulerPole('AN',90,0,1)}
        step=replace(parse_steps(line_step())[0],start=(0,0),end=(1,0))
        r=step_motion(step,p,radius_m=1000)
        self.assertAlmostEqual(r['opening_mm_a'],0,places=14)
        self.assertAlmostEqual(r['right_lateral_mm_a'],-math.pi/180,places=14)
    def test_source_polarity_does_not_follow_velocity_sign(self):
        s=parse_steps(line_step(kind='SUB',opening=1.2))[0]
        self.assertEqual(step_motion(s,fixture_poles())['kind'],'SUB')
    def test_missing_pole_refused(self):
        with self.assertRaises(ReferenceDataError):step_motion(parse_steps(line_step())[0],{})
    def test_antipodal_step_refused(self):
        s=replace(parse_steps(line_step())[0],start=(0,0),end=(180,0))
        with self.assertRaises(ReferenceDataError):step_motion(s,fixture_poles())
    def test_short_step_has_explicit_larger_rounding_allowance(self):
        s=parse_steps(line_step())[0]
        short=replace(s,start=(0,0),end=(.001,0))
        a=step_motion(s,fixture_poles());b=step_motion(short,fixture_poles())
        self.assertGreater(b['component_rounding_bound_mm_a'],a['component_rounding_bound_mm_a'])
        self.assertFalse(b['direction_resolved'])
    def test_radius_scaling_not_rate_fitting(self):
        s=parse_steps(line_step())[0];a=step_motion(s,fixture_poles());b=step_motion(s,fixture_poles(),radius_m=2*6371000)
        assert_allclose(b['opening_mm_a'],2*a['opening_mm_a'],rtol=2e-15)


class EvidencePolicy(unittest.TestCase):
    def test_all_area_values_remain_calibration(self):
        for name,_ in __import__('atlas_tectonics.plate_reference',fromlist=['AREA_ROWS']).AREA_ROWS:
            self.assertEqual(record_role(observable='area',plate_id=name),'CALIBRATION_PREVIOUSLY_EXPOSED')
    def test_same_plate_can_have_calibration_area_withheld_shape(self):
        self.assertIn('CALIBRATION',record_role(observable='area',plate_id='PS'))
        self.assertEqual(record_role(observable='outline',plate_id='PS'),'WITHHELD_WITHIN_MODEL')
    def test_prior_cocos_and_motion_exposure_retained(self):
        self.assertIn('PREVIOUSLY_EXPOSED',record_role(observable='outline',plate_id='CO'))
        self.assertIn('PREVIOUSLY_EXPOSED',record_role(observable='motion',boundary='AF-AN',step_number=1))
    def test_motion_split_uses_whole_neighbourhood(self):
        self.assertEqual(record_role(observable='motion',boundary='PA-PS',step_number=500),'WITHHELD_WITHIN_MODEL')
    def test_unknown_observables_refused(self):
        with self.assertRaises(ReferenceDataError):record_role(observable='wiggle_score')
    def test_protocol_hash_and_detachment(self):
        a=reference_protocol();b=reference_protocol();self.assertEqual(a['protocol_id'],b['protocol_id'])
        a['splits']['outline_withheld'].clear();self.assertEqual(len(reference_protocol()['splits']['outline_withheld']),10)
    def test_unavailable_history_does_not_become_static_success(self):
        r=reference_protocol();self.assertIn('not supplied',r['scientific_checks']['history'])
        self.assertTrue(all(v['status']=='NOT_ACQUIRED' for v in r['outstanding_reference_challenges']))
    def test_withheld_cannot_be_calibration(self):
        with self.assertRaises(ReferenceDataError):evaluation_record(ID,OTHER,split='withheld',run_id='trial',purpose='calibration')
    def test_use_record_never_grants_model_acceptance(self):
        r=evaluation_record(ID,OTHER,split='withheld',run_id='independent-trial',purpose='validation')
        self.assertFalse(r['geological_model_accepted']);self.assertEqual(r['independent_evidence_families'],1)
    def test_partial_dataset_cannot_generate_full_pass(self):
        fake=PB2002Dataset((),(),(),(),(),(),ID)
        with self.assertRaises(ReferenceDataError):reference_dataset_report(fake)
    def test_population_shape_requires_same_scale(self):
        with self.assertRaises(ReferenceDataError):compare_distributions([.5],[.6],metric='compactness',dataset_id=ID,candidate_id=OTHER,split='development',run_id='r',reference_scale_m=100000,candidate_scale_m=50000)
    def test_population_comparison_discloses_missing_plates(self):
        r=compare_distributions([.1,.5],[.2,.4],metric='compactness',dataset_id=ID,candidate_id=OTHER,split='withheld',run_id='r',reference_scale_m=100000,candidate_scale_m=100000,unresolved_candidate=3)
        self.assertEqual(r['unresolved_candidate'],3);self.assertIsNone(r['scientific_threshold']);self.assertFalse(r['geological_model_accepted'])
    def test_known_empirical_distribution_difference(self):
        r=compare_distributions([0,.5],[.5,1],metric='area_fraction',dataset_id=ID,candidate_id=OTHER,split='development',run_id='r')
        self.assertEqual(r['empirical_cdf_maximum_gap'],.5)
    def test_calibrated_area_cannot_be_rebranded_holdout(self):
        with self.assertRaises(ReferenceDataError):compare_distributions([.5],[.6],metric='area_fraction',dataset_id=ID,candidate_id=OTHER,split='withheld',run_id='r')


class StoreAndCLI(unittest.TestCase):
    def test_report_round_trip_dedup_and_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'r.db'
            with ArrayStore(path,StoreLimits(4096,1<<20,4<<20),Compression('raw')) as store:
                report=report_fixture();key=write_report_snapshot(report,store);n=store.statistics()['unique_chunks']
                self.assertEqual(read_report_snapshot(store,key),report)
                write_report_snapshot(report,store);self.assertEqual(n,store.statistics()['unique_chunks'])
                store.backup_to(Path(d)/'backup.db')
            path.unlink()
            with ArrayStore(Path(d)/'backup.db',StoreLimits(4096,1<<20,4<<20),Compression('raw')) as restored:
                self.assertEqual(read_report_snapshot(restored,key),report)
    def test_report_corruption_is_error(self):
        with tempfile.TemporaryDirectory() as d,ArrayStore(Path(d)/'r.db',StoreLimits(4096,1<<20,4<<20),Compression('raw')) as store:
            key=write_report_snapshot(report_fixture(),store)
            store._db.execute('UPDATE chunks SET payload=?',(b'corrupt',))
            with self.assertRaises(StoreError):read_report_snapshot(store,key)
    def test_concurrent_metrics_do_not_mutate_shared_input(self):
        p=np.eye(3);expected=spherical_ring_measures(p)
        with ThreadPoolExecutor(3) as pool:r=list(pool.map(lambda _:spherical_ring_measures(p),range(6)))
        self.assertTrue(all(v==expected for v in r));assert_array_equal(p,np.eye(3))
    def test_cli_missing_source_fails_closed(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            proc=subprocess.run([__import__('sys').executable,'-I','-B',str(ROOT/'tools/prepare_plate_reference.py'),'--verify-only','--data',d],capture_output=True,text=True,timeout=30)
            self.assertEqual(proc.returncode,2);self.assertIn('BLOCKED_REFERENCE_ACCEPTANCE',proc.stderr)
    def test_downloader_failure_never_publishes_partial_dataset(self):
        spec=importlib.util.spec_from_file_location('atlas_r1_acquire_test',ROOT/'tools/prepare_plate_reference.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'data'
            def bad(*args,**kwargs):raise OSError('network test failure')
            with self.assertRaises(OSError):m.acquire(target,opener=bad)
            self.assertFalse(target.exists());self.assertFalse(target.with_name('data.preparing').exists())
            self.assertEqual(list(Path(d).iterdir()),[])
    def test_downloader_does_not_overwrite_existing(self):
        spec=importlib.util.spec_from_file_location('atlas_r1_acquire_test2',ROOT/'tools/prepare_plate_reference.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'data';target.mkdir();(target/'keep').write_text('keep')
            with self.assertRaises(FileExistsError):m.acquire(target,opener=lambda *a,**k:None)
            self.assertEqual((target/'keep').read_text(),'keep')


class AdditionalResourceChecks(unittest.TestCase):
    def test_subnormal_spacing_refuses_before_integer_overflow(self):
        with self.assertRaises(ReferenceDataError):
            sample_ring_at_scale(np.eye(3),float(np.nextafter(0.,1.)))
    def test_curve_limit_before_capture(self):
        with mock.patch('atlas_tectonics.plate_reference_dataset.read_array',side_effect=AssertionError('captured')):
            with self.assertRaises(ReferenceDataError):
                ReferenceCurve('AA','plate','AA',1,np.zeros((20001,2)))
    def test_population_admission_precedes_copying(self):
        with self.assertRaises(MemoryLimitError):
            compare_distributions(np.ones(100),np.ones(100),metric='area_fraction',dataset_id=ID,
                candidate_id=OTHER,split='development',run_id='r',budget=WorkBudget(1))
    def test_normal_compressed_report_path(self):
        with tempfile.TemporaryDirectory() as d,ArrayStore(Path(d)/'r.db',StoreLimits(4096,1<<20,4<<20)) as store:
            r=report_fixture();key=write_report_snapshot(r,store)
            self.assertEqual(read_report_snapshot(store,key),r)


if __name__=='__main__':unittest.main()
