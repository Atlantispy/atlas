"""W01 stage 1: independent geometry/time cases and shared engineering contracts.

No Earth calibration, simulation, network or installed-data dependency. Scalar
trigonometry and hand-calculated bases serve as independent expected values;
round trips alone would not detect matching errors in forward/inverse routines.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import copy
import hashlib
import json
import math
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (
    SphericalFrame, LocalCartesianFrame, convert_angles, convert_lengths,
    east_south_up_to_enu, enu_to_east_south_up,
    TimeUnit, TimeAxis, EpochOffset, SECOND, JULIAN_YEAR, JULIAN_MEGAYEAR,
    advance_time, Rotation, rigid_velocity, TectonicsError,
)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics._validation import frozen
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.storage import ArrayStore, StoreLimits

ROOT = Path(__file__).resolve().parents[1]
CASE = json.loads((ROOT/'cases/w01_coordinates.json').read_text())
ATOL = CASE['acceptance']['angle_absolute_rad']
RTOL = CASE['acceptance']['relative_tolerance']
R = CASE['acceptance']['reference_radius_m']
SPHERE = SphericalFrame(R, 'synthetic-planet-axes')


def geometric_close(actual, expected, scale=R):
    # A dimensional roundoff envelope, chosen in the case BEFORE testing. This is
    # a coordinate representation bound, not a geological uncertainty/tolerance.
    assert_allclose(actual, expected, rtol=RTOL,
                    atol=CASE['acceptance']['scaled_position_roundoff_factor']*np.finfo(float).eps*scale)


def independent_xyz(lon, lat, height, radius):
    r = radius+height
    return [r*math.cos(lat)*math.cos(lon), r*math.cos(lat)*math.sin(lon),r*math.sin(lat)]


class SphericalTests(unittest.TestCase):
    def test_cardinal_positions(self):
        a = [[0,0,0],[90,0,0],[180,0,0],[-90,0,0],[35,90,0],[70,-90,0]]
        expected = np.array([[R,0,0],[0,R,0],[-R,0,0],[0,-R,0],[0,0,R],[0,0,-R]])
        geometric_close(SPHERE.to_cartesian(a,angle_unit='degrees'), expected)

    def test_scalar_independent_reference(self):
        a = [[.21,.42,123.],[-2.2,-.9,-100.],[math.pi-1e-10,1.4,0]]
        expected = [independent_xyz(*p,R) for p in a]
        geometric_close(SPHERE.to_cartesian(a),expected)

    def test_inverse_cardinals_and_canonical_seam(self):
        p = [[R,0,0],[-R,0,0],[0,R,0],[0,-R,0],[0,0,R],[0,0,-R]]
        result = SPHERE.to_spherical(p,angle_unit='degrees')
        assert_allclose(result[:,:2],[[0,0],[-180,0],[90,0],[-90,0],[0,90],[0,-90]],atol=ATOL)
        assert_array_equal(result[:,2],np.zeros(6))

    def test_poles_exact_xy_and_near_pole_not_snapped(self):
        exact = SPHERE.to_cartesian([[2,math.pi/2,0],[-1,-math.pi/2,0]])
        assert_array_equal(exact[:,:2],np.zeros((2,2)))
        lat = np.nextafter(math.pi/2,0.)
        p = SPHERE.to_cartesian([.7,lat,0])
        self.assertGreater(math.hypot(p[0],p[1]),0)
        self.assertAlmostEqual(float(SPHERE.to_spherical(p)[0]),.7,places=13)

    def test_seam_continuity(self):
        p=SPHERE.to_cartesian([[180-1e-6,0,0],[-180+1e-6,0,0]],angle_unit='degrees')
        self.assertLess(np.linalg.norm(p[0]-p[1]),.3)
        for lon in (180,-180,540,-540):
            assert_array_equal(SPHERE.to_cartesian([lon,0,0],angle_unit='degrees'),
                               SPHERE.to_cartesian([-180,0,0],angle_unit='degrees'))

    def test_tiny_negative_longitude_preserved(self):
        p=SPHERE.to_cartesian([-1e-20,0,0])
        self.assertLess(p[1],0)
        self.assertEqual(float(SPHERE.to_spherical(p)[0]),-1e-20)

    def test_round_trip_grid(self):
        rng=np.random.default_rng(71)
        a=np.column_stack((rng.uniform(-math.pi,math.pi,501),rng.uniform(-1.5,1.5,501),rng.uniform(-1e4,1e4,501)))
        restored=SPHERE.to_spherical(SPHERE.to_cartesian(a))
        assert_allclose(restored[:,:2],a[:,:2],rtol=RTOL,atol=ATOL)
        geometric_close(restored[:,2],a[:,2])

    def test_degree_radian_agreement(self):
        a=np.array([[25,45,0],[-125,-33,10.]])
        rad=a.copy();rad[:,:2]=np.deg2rad(rad[:,:2])
        geometric_close(SPHERE.to_cartesian(a,angle_unit='degrees'),SPHERE.to_cartesian(rad))

    def test_batches_strides_and_fortran(self):
        raw=np.tile([.4,.2,11.],(61,2,1))
        for a in (raw,raw[::2],np.asfortranarray(raw)):
            expected=SPHERE.to_cartesian(a)
            for chunk in CASE['acceptance']['test_batch_points']:
                assert_array_equal(SPHERE.to_cartesian(a,batch_points=chunk),expected)
                geometric_close(SPHERE.to_cartesian(SPHERE.to_spherical(expected,batch_points=chunk)),expected)

    def test_large_small_radius(self):
        for radius in (1e-150,1.,1e150):
            frame=SphericalFrame(radius,'scale')
            q=frame.to_spherical(frame.to_cartesian([.3,.4,0.]))
            assert_allclose(q[:2],[.3,.4],atol=ATOL)
            self.assertLessEqual(abs(q[2]),64*np.finfo(float).eps*radius)

    def test_inverse_hypot_large_coordinates(self):
        a=SphericalFrame(1e308,'huge').to_spherical([1e308,1e308,0.])
        self.assertTrue(np.isfinite(a).all())
        self.assertAlmostEqual(a[0],math.pi/4)

    def test_invalid_radius_and_frames(self):
        for r in (0,-1,True,np.inf,np.nan,'2'):
            with self.subTest(r=r),self.assertRaises(TectonicsError):SphericalFrame(r,'x')
        for name in ('',' '*2,7,'a'*257):
            with self.assertRaises(TectonicsError):SphericalFrame(1,name)

    def test_centre_and_invalid_height(self):
        for p in ([0,0,-R],[0,0,-R-1],[0,0,np.inf],[0,0,1e-20]):
            with self.assertRaises(TectonicsError):SPHERE.to_cartesian(p)
        with self.assertRaises(TectonicsError):SPHERE.to_spherical([0,0,0])

    def test_latitude_and_units_rejected(self):
        for lat in (math.pi/2+1e-6,-math.pi/2-1e-6):
            with self.assertRaises(TectonicsError):SPHERE.to_cartesian([0,lat,0])
        with self.assertRaises(TectonicsError):SPHERE.to_cartesian([0,91,0],angle_unit='degrees')
        with self.assertRaises(TectonicsError):SPHERE.to_cartesian([0,0,0],angle_unit='auto')

    def test_mask_bool_nonfinite_shape_refused(self):
        for p in (np.ma.array([0.,0,0]),[True,0,0],[np.nan,0,0],[[1,2]],[],[[1,2,3],[1,2]]):
            with self.subTest(p=str(p)),self.assertRaises(TectonicsError):SPHERE.to_cartesian(p)

    def test_budget_refuses_before_copy(self):
        p=np.zeros((100,3))
        with mock.patch('numpy.empty',side_effect=AssertionError('allocated')):
            with self.assertRaises(MemoryLimitError):SPHERE.to_cartesian(p,budget=WorkBudget(16))
        with mock.patch('numpy.array',side_effect=AssertionError('copied')):
            with self.assertRaises(TectonicsError):SPHERE.to_spherical(np.zeros((10,2)))

    def test_immutable_and_nonalias(self):
        a=np.array([.2,.4,10]);original=a.copy();out=SPHERE.to_cartesian(a)
        a[:]=0;geometric_close(out,independent_xyz(*original,R))
        with self.assertRaises(ValueError):out.setflags(write=True)
        with self.assertRaises(FrozenInstanceError):SPHERE.radius_m=1

    def test_identity_changes_with_radius_and_reference(self):
        self.assertNotEqual(SPHERE.identity,replace(SPHERE,radius_m=2*R).identity)
        self.assertNotEqual(SPHERE.identity,replace(SPHERE,frame_id='other').identity)
        self.assertEqual(SPHERE.identity,SphericalFrame(R,'synthetic-planet-axes').identity)


class LocalFrameTests(unittest.TestCase):
    def setUp(self):
        self.frame=LocalCartesianFrame(SPHERE,'regional',.3,.6,30.)

    def test_origin_and_independent_equator_basis(self):
        f=LocalCartesianFrame(SPHERE,'equator',0.,0.)
        assert_array_equal(f.positions_from_cartesian([R,0,0]),[0,0,0])
        assert_allclose(f.basis,[[0,0,1],[1,0,0],[0,1,0]],atol=ATOL)
        geometric_close(f.positions_to_cartesian([3,4,5]),[R+5,3,4])

    def test_unresolvable_local_position_refused(self):
        with self.assertRaises(TectonicsError):
            self.frame.positions_to_cartesian([1e-50,1e-50,1e-50])

    def test_basis_orthonormal_and_right_handed(self):
        for lat in (-math.pi/2,-.5,0,.5,math.pi/2):
            for heading in (0.,.3,math.pi/2):
                f=LocalCartesianFrame(SPHERE,'test',1.2,lat,axis_rotation_rad=heading)
                assert_allclose(f.basis.T@f.basis,np.eye(3),atol=ATOL)
                self.assertAlmostEqual(np.linalg.det(f.basis),1.,places=13)

    def test_local_axis_rotation(self):
        f=LocalCartesianFrame(SPHERE,'north-facing',0.,0.,axis_rotation_rad=math.pi/2)
        geometric_close(f.vectors_to_cartesian([1,0,0]),[0,0,1],1.)
        geometric_close(f.vectors_to_cartesian([0,1,0]),[0,-1,0],1.)

    def test_polar_meridian_is_explicit_orientation(self):
        a=LocalCartesianFrame(SPHERE,'pole-a',0.,math.pi/2)
        b=LocalCartesianFrame(SPHERE,'pole-b',math.pi/2,math.pi/2)
        assert_array_equal(a.origin_m,b.origin_m)
        self.assertFalse(np.allclose(a.basis,b.basis))
        assert_allclose(a.basis[:,0],[0,1,0],atol=ATOL)
        assert_allclose(b.basis[:,0],[-1,0,0],atol=ATOL)

    def test_vector_transform_never_subtracts_origin(self):
        f=LocalCartesianFrame(SPHERE,'equator',0.,0.)
        assert_allclose(f.vectors_from_cartesian([1,2,3]),[2,3,1],atol=ATOL)
        self.assertFalse(np.allclose(f.positions_from_cartesian([1,2,3]),[2,3,1]))

    def test_local_roundtrips_and_distances(self):
        x=np.array([[10.,20,30],[-100,22,99],[0,0,0]])
        world=self.frame.positions_to_cartesian(x)
        geometric_close(self.frame.positions_from_cartesian(world),x)
        geometric_close(np.linalg.norm(world[1]-world[0]),np.linalg.norm(x[1]-x[0]))

    def test_full_up_component_retains_curvature(self):
        f=LocalCartesianFrame(SPHERE,'equator',0.,0.)
        local=f.positions_from_cartesian(SPHERE.to_cartesian([.2,0,0]))
        self.assertLess(local[2],0)
        self.assertAlmostEqual(local[0]/R,math.sin(.2))
        self.assertAlmostEqual(local[2]/R,math.cos(.2)-1)
        self.assertNotAlmostEqual(local[0],R*.2)

    def test_direct_reframe_positions_and_vectors(self):
        target=LocalCartesianFrame(SPHERE,'other',-.8,.1,-100.,-.2)
        x=np.arange(42.).reshape(2,7,3)
        geometric_close(self.frame.to_frame(x,target,kind='position'),
                         target.positions_from_cartesian(self.frame.positions_to_cartesian(x)))
        geometric_close(self.frame.to_frame(x,target,kind='vector'),
                         target.vectors_from_cartesian(self.frame.vectors_to_cartesian(x)),100.)

    def test_other_parent_and_ambiguous_kind_refused(self):
        for s in (SphericalFrame(R,'other-world-axes'),SphericalFrame(R+1,SPHERE.frame_id)):
            target=LocalCartesianFrame(s,'target',0,0)
            with self.assertRaises(TectonicsError):self.frame.to_frame([1,2,3],target,kind='vector')
        with self.assertRaises(TectonicsError):self.frame.to_frame([1,2,3],self.frame,kind='velocity-auto')

    def test_moving_frame_comoving_point_zero_velocity(self):
        local=np.array([[1.,2,3],[4,5,6]])
        p=self.frame.positions_to_cartesian(local)
        v0=np.array([2.,3,4]);omega=np.array([.01,-.02,.03])
        v=v0+np.cross(omega,p-self.frame.origin_m)
        result=self.frame.velocity_from_cartesian(p,v,origin_velocity_m_s=v0,angular_velocity_rad_s=omega)
        assert_allclose(result,np.zeros_like(local),atol=ATOL)

    def test_moving_frame_velocity_inverse(self):
        x=np.array([[1.,2,3],[10,20,30]]);v=np.array([[.1,.2,.3],[.4,-.5,.6]])
        args=dict(origin_velocity_m_s=[1.,2,3],angular_velocity_rad_s=[.01,.02,.03])
        world=self.frame.velocity_to_cartesian(x,v,**args)
        restored=self.frame.velocity_from_cartesian(self.frame.positions_to_cartesian(x),world,**args)
        geometric_close(restored,v,scale=R*.03)

    def test_static_velocity_agrees_with_vector_components(self):
        v=np.array([[1.,2,3]])
        a=self.frame.velocity_from_cartesian([self.frame._origin],v,
             origin_velocity_m_s=[0,0,0],angular_velocity_rad_s=[0,0,0])
        assert_array_equal(a,self.frame.vectors_from_cartesian(v))

    def test_velocity_requires_position_and_explicit_rates(self):
        with self.assertRaises(TypeError):self.frame.velocity_from_cartesian([1,2,3],[1,2,3])
        with self.assertRaises(TectonicsError):self.frame.velocity_from_cartesian(
            [[1,2,3]],[1,2,3],origin_velocity_m_s=[0,0,0],angular_velocity_rad_s=[0,0,0])

    def test_live_metadata_cannot_mutate_basis(self):
        matrix=self.frame.basis;matrix.shape=(9,)
        self.assertEqual(self.frame.basis.shape,(3,3))
        with self.assertRaises(ValueError):self.frame.basis.setflags(write=True)
        d=self.frame.descriptor();d['sphere']['radius_m']=0
        self.assertEqual(self.frame.sphere.radius_m,R)

    def test_pickle_deepcopy_restore_immutable_basis(self):
        for other in (pickle.loads(pickle.dumps(self.frame)),copy.deepcopy(self.frame)):
            self.assertEqual(other.identity,self.frame.identity)
            assert_array_equal(other.basis,self.frame.basis)
            with self.assertRaises(ValueError):other.basis.setflags(write=True)

    def test_frame_identity_covers_all_geometry(self):
        for field,value in [('frame_id','renamed'),('longitude_rad',.4),('latitude_rad',.7),
                            ('height_m',40),('axis_rotation_rad',.5)]:
            self.assertNotEqual(self.frame.identity,replace(self.frame,**{field:value}).identity)

    def test_latitude_and_bad_names_refused(self):
        for kwargs in ({'latitude_rad':2.},{'frame_id':''},{'height_m':-R}):
            with self.assertRaises(TectonicsError):replace(self.frame,**kwargs)

    def test_batch_and_shared_budget_thread_results(self):
        points=frozen(np.arange(600.).reshape(200,3))
        b=WorkBudget(8<<20)
        expected=self.frame.positions_to_cartesian(points,budget=b)
        def work(i):return self.frame.positions_to_cartesian(points,budget=b,batch_points=i+1)
        with ThreadPoolExecutor(2) as pool:
            for result in pool.map(work,[6,10,42]):geometric_close(result,expected)
        self.assertEqual(b.reserved_bytes,0)

    def test_budget_release_on_invalid_and_overflow(self):
        budget=WorkBudget(2<<20)
        for call in (lambda:self.frame.positions_to_cartesian([np.inf,0,0],budget=budget),
                     lambda:SphericalFrame(1e308,'huge').to_spherical([1.7e308]*3,budget=budget)):
            with self.assertRaises(TectonicsError):call()
            self.assertEqual(budget.reserved_bytes,0)

    def test_finite_rotation_then_frame_invariants(self):
        p=SPHERE.to_cartesian([[.2,.1,0],[.3,.4,0],[.4,-.3,0]])
        moved=Rotation.from_axis_angle([1,2,3],.5).apply(p)
        regional=self.frame.positions_from_cartesian(moved)
        geometric_close(np.linalg.norm(np.diff(regional,axis=0),axis=1),
                         np.linalg.norm(np.diff(p,axis=0),axis=1))


class ConventionTests(unittest.TestCase):
    def test_length_and_angle_units(self):
        assert_array_equal(convert_lengths([1.,2.5],source='km',target='m'),[1000,2500])
        assert_allclose(convert_angles([0,90,180],source='degrees',target='radians'),[0,math.pi/2,math.pi],atol=ATOL)
        assert_allclose(convert_angles([0,math.pi/2],source='radians',target='degrees'),[0,90],atol=ATOL)

    def test_no_angle_wrapping_for_angular_rate_units(self):
        a=convert_angles([720,-360],source='degrees',target='radians')
        assert_allclose(a,[4*math.pi,-2*math.pi],atol=ATOL)

    def test_invalid_units_and_unrepresentable_conversion(self):
        with self.assertRaises(TectonicsError):convert_angles([1],source='deg',target='radians')
        with self.assertRaises(TectonicsError):convert_lengths([1e308],source='km',target='m')
        with self.assertRaises(TectonicsError):convert_lengths([np.nextafter(0.,1.)],source='m',target='km')
        with self.assertRaises(MemoryLimitError):convert_lengths([1,2,3],source='m',target='km',budget=WorkBudget(1))

    def test_legacy_reflection_and_inverse(self):
        a=[[1.,2,3],[-4,5,-6]]
        enu=east_south_up_to_enu(a)
        assert_array_equal(enu,[[1,-2,3],[-4,-5,-6]])
        assert_array_equal(enu_to_east_south_up(enu),a)

    def test_legacy_axial_rule_preserves_cross_product(self):
        a=np.array([1.,2,3]);b=np.array([4.,-2,7])
        actual=east_south_up_to_enu(np.cross(a,b),axial=True)
        expected=np.cross(east_south_up_to_enu(a),east_south_up_to_enu(b))
        assert_array_equal(actual,expected)
        assert_array_equal(enu_to_east_south_up(actual,axial=True),np.cross(a,b))

    def test_legacy_invalid_kind_and_layout(self):
        with self.assertRaises(TectonicsError):east_south_up_to_enu([1,2,3],axial='yes')
        with self.assertRaises(TectonicsError):east_south_up_to_enu([1,2])

    def test_new_apis_keep_mask_and_shape_safeguards(self):
        a=np.ma.array([1.,2,3],mask=False)
        for call in (lambda:convert_lengths(a,source='m',target='km'),
                     lambda:east_south_up_to_enu(a)):
            with self.assertRaises(TectonicsError):call()


class TimeTests(unittest.TestCase):
    def setUp(self):
        self.forward=TimeAxis('synthetic-epoch',SECOND,0.)
        self.before=TimeAxis('synthetic-epoch',JULIAN_MEGAYEAR,0.,'before')

    def test_explicit_julian_duration(self):
        self.assertEqual(JULIAN_YEAR.seconds_per_unit,365.25*86400)
        self.assertEqual(JULIAN_MEGAYEAR.seconds_per_unit,1e6*JULIAN_YEAR.seconds_per_unit)

    def test_forward_and_before_mapping(self):
        assert_array_equal(self.before.to_seconds([1.,2]),[-31557600000000.,-63115200000000.])
        assert_array_equal(self.before.from_seconds([-31557600000000.,0]),[1.,0])
        self.assertLess(self.before.to_seconds(2.),self.before.to_seconds(1.))

    def test_nonzero_present_origin(self):
        axis=TimeAxis('e',SECOND,100.,'before')
        assert_array_equal(axis.to_seconds([10,20]),[90,80])
        assert_array_equal(axis.from_seconds([90,80]),[10,20])

    def test_durations_forward_for_before_axis(self):
        assert_array_equal(self.before.duration_to_seconds([0,1]),[0,JULIAN_MEGAYEAR.seconds_per_unit])
        with self.assertRaises(TectonicsError):self.before.duration_to_seconds(-1)

    def test_rate_sign_and_units(self):
        self.assertEqual(self.before.rate_to_per_second(1),-1/JULIAN_MEGAYEAR.seconds_per_unit)
        omega=convert_angles(1.,source='degrees',target='radians')
        rate=self.before.rate_to_per_second(omega)
        self.assertLess(rate,0)
        dt=self.before.duration_to_seconds(1.)
        self.assertAlmostEqual(float(rate*dt),-math.pi/180)

    def test_axes_round_trip_and_strided_input(self):
        axis=TimeAxis('synthetic-epoch',TimeUnit('ten seconds',10),100,'before')
        a=np.arange(-20.,20.).reshape(5,8)[:,::2]
        assert_array_equal(axis.convert(a,self.forward),100-10*a)
        assert_array_equal(self.forward.convert(axis.convert(a,self.forward),axis),a)

    def test_explicit_epoch_bridge(self):
        other=TimeAxis('other',SECOND,10.)
        bridge=EpochOffset('synthetic-epoch','other',100.)
        assert_array_equal(self.forward.convert([1,2],other,epoch_offset=bridge),[91,92])
        assert_array_equal(other.convert([91,92],self.forward,epoch_offset=bridge.inverse()),[1,2])

    def test_mismatched_epoch_and_bridge_refused(self):
        other=TimeAxis('other',SECOND,0)
        with self.assertRaises(TectonicsError):self.forward.convert([1],other)
        with self.assertRaises(TectonicsError):self.forward.convert([1],other,epoch_offset=EpochOffset('wrong','other',0))
        with self.assertRaises(TectonicsError):EpochOffset('same','same',1)

    def test_same_origin_direct_conversion_retains_small_intervals(self):
        axis=TimeAxis('e',SECOND,1e20)
        other=TimeAxis('e',TimeUnit('tenth second',.1),1e20)
        assert_array_equal(axis.convert([.01,.1,1.],axis),[.01,.1,1.])
        assert_allclose(axis.convert([.01,.1,1.],other),[.1,1,10],atol=ATOL)
        with self.assertRaises(TectonicsError):axis.to_seconds(1.)

    def test_advance_time_refuses_lost_or_invalid_step(self):
        self.assertEqual(advance_time(10.,2.),12.)
        self.assertEqual(advance_time(2.,0.),2.)
        for t,d in ((1e20,1),(0,-1),(0,True),(1e308,1e308)):
            with self.assertRaises(TectonicsError):advance_time(t,d)

    def test_model_duration_does_not_relabel_w02(self):
        from atlas_tectonics import ColumnGrid1D, MaterialCohort, MaterialState
        grid=ColumnGrid1D([0,1,2],frame_id='e')
        formed=float(self.before.to_seconds(1))
        state=MaterialState(grid,(MaterialCohort('a','rock','origin',formed),),
                            np.ones((1,2)),time_s=0,epoch_id=self.before.epoch_id)
        self.assertEqual(state.cohorts[0].formation_time_s,formed)
        self.assertEqual(state.epoch_id,self.before.epoch_id)

    def test_time_overflow_underflow(self):
        with self.assertRaises(TectonicsError):self.before.to_seconds(1e308)
        with self.assertRaises(TectonicsError):TimeAxis('e',TimeUnit('tiny',1e-300),0).duration_to_seconds(1e-300)
        with self.assertRaises(TectonicsError):TimeAxis('e',TimeUnit('huge',1e300),0).from_seconds(1e-300)

    def test_invalid_time_configuration(self):
        for value in (0,-1,True,np.inf):
            with self.assertRaises(TectonicsError):TimeUnit('unit',value)
        for change in ({'direction':'backwards-auto'},{'unit':'years'},{'epoch_id':''}):
            with self.assertRaises(TectonicsError):replace(self.forward,**change)

    def test_time_identity_and_restore(self):
        restored=pickle.loads(pickle.dumps(self.before))
        self.assertEqual(restored.identity,self.before.identity)
        for key,value in [('epoch_id','changed'),('direction','forward'),('zero_time_s',100),('unit',SECOND)]:
            self.assertNotEqual(self.before.identity,replace(self.before,**{key:value}).identity)

    def test_time_output_immutable_nonalias(self):
        a=np.arange(10.)
        out=self.before.to_seconds(a);a[:]=0
        self.assertNotEqual(out[1],0)
        with self.assertRaises(ValueError):out.setflags(write=True)

    def test_time_masks_and_budget_refused(self):
        b=WorkBudget(16)
        with self.assertRaises(MemoryLimitError):self.before.to_seconds(np.ones(8),budget=b)
        self.assertEqual(b.reserved_bytes,0)
        for value in (np.ma.array([1.]),[True,1.],[],[np.nan]):
            with self.assertRaises(TectonicsError):self.before.to_seconds(value)


class IntegrationTests(unittest.TestCase):
    def test_descriptors_storage_and_identity_no_new_cache(self):
        frame=LocalCartesianFrame(SPHERE,'region',.2,.3)
        with tempfile.TemporaryDirectory() as tmp, ArrayStore(Path(tmp)/'coords.db',StoreLimits(1024,1<<20,4<<20)) as store:
            out=frame.positions_to_cartesian(np.arange(300.).reshape(100,3))
            store.put(frame.identity,{'position_m':out},frame.descriptor())
            restored=store.get(frame.identity)['position_m']
            assert_array_equal(out,restored)
            self.assertEqual(store.metadata(frame.identity),frame.descriptor())
            with self.assertRaises(ValueError):restored.setflags(write=True)

    def test_execution_context_sees_new_conversions(self):
        with ExecutionContext('scipy') as ctx:
            ctx.verify()
            import atlas_tectonics.coordinates as coords
            fn=coords.convert_angles
            def replacement(*a,**k):return np.zeros(1)
            replacement.__module__=coords.__name__
            with mock.patch.object(coords,'convert_angles',replacement):
                with self.assertRaises(TectonicsError):ctx.verify()
            self.assertIs(coords.convert_angles,fn)

    def test_execution_context_sees_time_unit_definitions(self):
        import atlas_tectonics.timebase as tb
        with ExecutionContext('scipy') as ctx:
            with mock.patch.object(tb,'SECOND',TimeUnit('changed second',2.)):
                with self.assertRaises(TectonicsError):ctx.verify()

    def test_fresh_process_frame_and_time_restore(self):
        frame=LocalCartesianFrame(SPHERE,'region',.4,.6,20.,.3)
        axis=TimeAxis('epoch',JULIAN_YEAR,0.,'before')
        expected=frame.positions_to_cartesian([[1.,2,3]]).tobytes()
        script='''import sys,pickle,hashlib
sys.path.insert(0,sys.argv[1])
f,t=pickle.load(open(sys.argv[2],"rb"))
a=f.positions_to_cartesian([[1.,2,3]])
print(hashlib.sha256(a.tobytes()).hexdigest(), t.identity, a.flags.writeable)
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'frames.pkl';p.write_bytes(pickle.dumps((frame,axis)))
            done=subprocess.run([sys.executable,'-I','-B','-c',script,str(ROOT/'src'),str(p)],
                                 capture_output=True,text=True,timeout=20)
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(done.stdout.strip(),f'{hashlib.sha256(expected).hexdigest()} {axis.identity} False')


if __name__ == '__main__':
    unittest.main()
