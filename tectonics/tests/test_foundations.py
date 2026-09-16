"""Analytical and finite-volume verification, not geological validation.

Expected values are derived independently of implementation where possible.
All material constants in foundations.json are synthetic, not Earth calibration.
"""
from dataclasses import FrozenInstanceError, replace
import json
import math
from pathlib import Path
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (
    TectonicsError, ThermalParameters, FlexureParameters, PeriodicGrid1D,
    Rotation, boundary_motion, rigid_velocity, advect_thickness,
    half_space_temperature, PeriodicFlexure, identity,
)
from atlas_tectonics._validation import array, scalar

CASE = json.loads((Path(__file__).resolve().parents[1] / 'cases/foundations.json').read_text())
THERMAL = ThermalParameters(**CASE['thermal'])
ELASTIC = FlexureParameters(**CASE['flexure'])
ATOL = CASE['acceptance']['absolute_tolerance']
RTOL = CASE['acceptance']['relative_tolerance']


def close(actual, expected):
    assert_allclose(actual, expected, atol=ATOL, rtol=RTOL)


def dense_operator(grid, material):
    """Independent real-space assembly, no FFT or solver transfer coefficients."""
    n, dx = grid.cells, grid.spacing_m
    matrix = np.zeros((n, n))
    for i in range(n):
        for offset, coefficient in ((-2, 1), (-1, -4), (0, 6), (1, -4), (2, 1)):
            matrix[i, (i + offset) % n] += material.rigidity_n_m * coefficient / dx**4
        matrix[i, i] += material.restoring_pa_per_m
    return matrix


class ParameterTests(unittest.TestCase):
    def test_frozen_records(self):
        with self.assertRaises(FrozenInstanceError):
            THERMAL.diffusivity_m2_s = 2

    def test_derived_rigidity_and_restoration(self):
        self.assertEqual(ELASTIC.rigidity_n_m, 1)
        self.assertEqual(ELASTIC.restoring_pa_per_m, 1)
        self.assertEqual(replace(ELASTIC, elastic_thickness_m=2).rigidity_n_m, 8)

    def test_deterministic_identity_and_resolved_round_trip(self):
        from dataclasses import asdict
        restored = ThermalParameters(**json.loads(json.dumps(asdict(THERMAL))))
        self.assertEqual(identity(THERMAL), identity(restored))
        self.assertEqual(identity(THERMAL), identity(ThermalParameters(**CASE['thermal'])))

    def test_every_physical_parameter_changes_identity(self):
        for field in ('young_modulus_pa', 'elastic_thickness_m', 'density_contrast_kg_m3', 'gravity_m_s2'):
            with self.subTest(field=field):
                changed = replace(ELASTIC, **{field: getattr(ELASTIC, field)*2})
                self.assertNotEqual(identity(ELASTIC), identity(changed))
        self.assertNotEqual(identity(ELASTIC), identity(replace(ELASTIC, poisson_ratio=.1)))

    def test_no_implicit_physical_defaults(self):
        with self.assertRaises(TypeError):
            ThermalParameters()
        with self.assertRaises(TypeError):
            FlexureParameters()

    def test_invalid_numbers_and_signs(self):
        for value in (True, '1', float('nan'), float('inf'), -1., 0.):
            with self.subTest(value=value), self.assertRaises(TectonicsError):
                replace(THERMAL, diffusivity_m2_s=value)
        for value in (-1., .5, 1., True):
            with self.subTest(value=value), self.assertRaises(TectonicsError):
                replace(ELASTIC, poisson_ratio=value)

    def test_temperature_order_and_text(self):
        with self.assertRaises(TectonicsError):
            replace(THERMAL, mantle_temperature_k=200.)
        with self.assertRaises(TectonicsError):
            replace(THERMAL, surface_temperature_k=-1.)
        with self.assertRaises(TectonicsError):
            replace(ELASTIC, provenance=' ')

    def test_grid_validation(self):
        for cells in (True, 4, 5.5):
            with self.subTest(cells=cells), self.assertRaises(TectonicsError):
                PeriodicGrid1D(cells, 10.)
        for length in (0., -1., float('inf')):
            with self.subTest(length=length), self.assertRaises(TectonicsError):
                PeriodicGrid1D(8, length)

    def test_overflow_refused_not_clamped(self):
        with self.assertRaises(TectonicsError):
            replace(ELASTIC, elastic_thickness_m=1e200)
        with self.assertRaises(TectonicsError):
            scalar(10**1000, 'huge')

    def test_array_rejects_nonphysical_types(self):
        for value in ([True, 1.], ['1', '2'], [1+0j], [], [np.nan], [[1], [2, 3]]):
            with self.subTest(value=value), self.assertRaises(TectonicsError):
                array(value, 'field')


class RotationTests(unittest.TestCase):
    def test_quarter_turn_and_pole(self):
        rotation = Rotation.from_axis_angle([0, 0, 1], math.pi/2)
        close(rotation.apply([[1,0,0], [0,1,0], [0,0,1]]), [[0,1,0], [-1,0,0], [0,0,1]])

    def test_unit_normalisation(self):
        close(Rotation((4,0,0,0)).apply([3,2,1]), [3,2,1])
        close(Rotation.from_axis_angle([0,0,4], .3).apply([1,2,3]),
              Rotation.from_axis_angle([0,0,1], .3).apply([1,2,3]))

    def test_inverse_restores_batch(self):
        points = np.arange(24.).reshape(2,4,3) - 10
        rotation = Rotation.from_axis_angle([1,2,3], .7)
        close(rotation.inverse().apply(rotation.apply(points)), points)

    def test_composition_order_is_not_commutative(self):
        a = Rotation.from_axis_angle([1,0,0], math.pi/2)
        b = Rotation.from_axis_angle([0,0,1], math.pi/2)
        close(a.then(b).apply([0,1,0]), [0,0,1])
        close(b.then(a).apply([0,1,0]), [-1,0,0])
        close(a.then(b).apply([1,2,3]), b.apply(a.apply([1,2,3])))

    def test_distances_orthogonality_and_orientation(self):
        r = Rotation.from_axis_angle([2,-4,1], 1.2)
        matrix = r.apply(np.eye(3))
        close(matrix @ matrix.T, np.eye(3))
        close(np.linalg.det(matrix), 1.)
        points = np.array([[1,2,3],[-2,4,7],[5,1,-4.]])
        close(np.linalg.norm(np.diff(r.apply(points), axis=0), axis=1),
              np.linalg.norm(np.diff(points, axis=0), axis=1))

    def test_zero_and_full_turn(self):
        for angle in (0., 2*math.pi, -2*math.pi):
            close(Rotation.from_axis_angle([1,0,0], angle).apply([1,2,3]), [1,2,3])

    def test_antipodal_quaternions_same_rotation(self):
        close(Rotation((1,2,3,4)).apply([2,1,4]), Rotation((-1,-2,-3,-4)).apply([2,1,4]))

    def test_velocity_is_instantaneous_tangential(self):
        close(rigid_velocity([[2,0,0],[0,2,0],[0,0,2]], [0,0,3]), [[0,6,0],[-6,0,0],[0,0,0]])
        p = np.array([[2.,3,4],[4,-1,2]])
        close(np.sum(p * rigid_velocity(p, [1,2,3]), axis=1), [0,0])

    def test_inputs_and_results_cannot_alias(self):
        p = np.array([[1.,0,0]])
        r = Rotation.from_axis_angle([0,0,1], math.pi/2).apply(p)
        assert_array_equal(p, [[1.,0,0]])
        p[:] = 8
        close(r, [[0,1,0]])
        with self.assertRaises(ValueError):
            r.setflags(write=True)

    def test_invalid_rotation_inputs(self):
        for q in ((0,0,0,0), (1,2,3), (True,0,0,0), (1,np.inf,0,0)):
            with self.subTest(q=q), self.assertRaises(TectonicsError):
                Rotation(q)
        with self.assertRaises(TectonicsError):
            Rotation.from_axis_angle([0,0,0], 0)
        with self.assertRaises(TectonicsError):
            Rotation((1,0,0,0)).apply([1,2])
        with self.assertRaises(TectonicsError):
            rigid_velocity([1e308,1e308,0], [0,0,1e308])


class BoundaryTests(unittest.TestCase):
    def test_east_trace_right_side_is_south(self):
        m = boundary_motion([0,0], [3,-4], [10,0], [1,2])
        close(m.right_normal, [0,-1])
        self.assertEqual(m.opening_m_s, 4)
        self.assertEqual(m.tangential_m_s, 3)
        close(m.right_relative_to_boundary_m_s, [2,-6])

    def test_north_trace_right_side_is_east(self):
        m = boundary_motion([0,0], [3,4], [0,2], [0,0])
        self.assertEqual(m.opening_m_s, 3)
        self.assertEqual(m.tangential_m_s, 4)

    def test_side_and_trace_reversal(self):
        a = boundary_motion([1,2], [4,6], [1,2], [-1,0])
        b = boundary_motion([4,6], [1,2], [-1,-2], [-1,0])
        close([a.opening_m_s,a.tangential_m_s], [b.opening_m_s,b.tangential_m_s])

    def test_common_frame_translation(self):
        frame = np.array([10,-7])
        a = boundary_motion([1,2], [3,4], [1,1], [5,6])
        b = boundary_motion(np.array([1,2])+frame, np.array([3,4])+frame, [1,1], np.array([5,6])+frame)
        self.assertEqual(a,b)

    def test_boundary_motion_does_not_change_interplate_motion(self):
        a = boundary_motion([1,2], [3,4], [1,0], [0,0])
        b = boundary_motion([1,2], [3,4], [1,0], [5,6])
        self.assertEqual(a.opening_m_s,b.opening_m_s)
        self.assertNotEqual(a.left_relative_to_boundary_m_s,b.left_relative_to_boundary_m_s)

    def test_zero_tangent_and_nonfinite_refused(self):
        with self.assertRaises(TectonicsError):
            boundary_motion([0,0],[0,0],[0,0],[0,0])
        with self.assertRaises(TectonicsError):
            boundary_motion([0,0],[np.inf,0],[1,0],[0,0])


class TransportTests(unittest.TestCase):
    def test_unit_courant_shift_both_directions(self):
        grid = PeriodicGrid1D(8,8)
        h = np.arange(8., dtype=float)
        for sign in (-1.,1.):
            result = advect_thickness(h,np.full(8,sign),grid,1)
            assert_array_equal(result.thickness_m,np.roll(h,int(sign)))
            self.assertEqual(result.balance_residual_m2,0)

    def test_fractional_step_matches_independent_flux_loop(self):
        grid = PeriodicGrid1D(9,9)
        h = np.arange(9.) / 3
        u = np.array([.2,-.4,.1,.3,-.3,.7,0,.2,-.5])
        dt = .4
        faces = [u[i] * (h[i] if u[i]>=0 else h[(i+1)%9]) for i in range(9)]
        expected = [h[i] - dt * (faces[i]-faces[(i-1)%9]) for i in range(9)]
        result = advect_thickness(h,u,grid,dt)
        close(result.thickness_m,expected)
        close(result.face_flux_m2_s,faces)
        close(result.balance_residual_m2,0)
        self.assertTrue(np.all(result.thickness_m>=0))

    def test_variable_velocity_changes_constant_thickness(self):
        grid=PeriodicGrid1D(8,8)
        u=np.array([.2,.1,0,-.1,0,.1,0,0])
        result=advect_thickness(np.ones(8),u,grid,1)
        close(result.thickness_m,1-(u-np.roll(u,1)))
        self.assertFalse(np.allclose(result.thickness_m,1))

    def test_outgoing_sum_courant_guard(self):
        u=np.zeros(8); u[0]=.75; u[-1]=-.75
        with self.assertRaisesRegex(TectonicsError,'Courant'):
            advect_thickness(np.ones(8),u,PeriodicGrid1D(8,8),1)

    def test_no_clamp_and_closed_budget_over_small_history(self):
        grid=PeriodicGrid1D(32,1)
        h=np.zeros(32); h[5:10]=1
        before=h.sum()*grid.spacing_m
        for _ in range(32):
            r=advect_thickness(h,np.full(32,1.),grid,.5*grid.spacing_m)
            self.assertTrue(np.all(r.thickness_m>=0))
            h=r.thickness_m
        close(h.sum()*grid.spacing_m,before)

    def test_first_order_smooth_convergence(self):
        errors=[]
        for n in (32,64,128):
            grid=PeriodicGrid1D(n,1)
            x=(np.arange(n)+.5)/n
            averaging=np.sinc(1/n)
            h=2+averaging*np.sin(2*np.pi*x)
            for _ in range(n//2):
                h=advect_thickness(h,np.ones(n),grid,.5/n).thickness_m
            target=2+averaging*np.sin(2*np.pi*(x-.25))
            errors.append(np.mean(np.abs(h-target)))
        order=np.log2(np.array(errors[:-1])/errors[1:])
        self.assertTrue(np.all(order>CASE['acceptance']['smooth_transport_order_min']),order)
        self.assertTrue(np.all(order<CASE['acceptance']['smooth_transport_order_max']),order)

    def test_zero_time_and_velocity(self):
        grid=PeriodicGrid1D(8,8); h=np.arange(8.)
        assert_array_equal(advect_thickness(h,np.zeros(8),grid,10).thickness_m,h)
        assert_array_equal(advect_thickness(h,np.ones(8),grid,0).thickness_m,h)

    def test_rejection_preserves_inputs(self):
        h=np.arange(8.); before=h.copy()
        with self.assertRaises(TectonicsError):
            advect_thickness(h,np.ones(8),PeriodicGrid1D(8,8),2)
        assert_array_equal(h,before)

    def test_shape_sign_and_nonfinite(self):
        grid=PeriodicGrid1D(8,8)
        for h,u,dt in (([-1]*8,[1]*8,.1),([1]*7,[1]*8,.1),([1]*8,[1]*8,-1),([1]*8,[True]*8,.1)):
            with self.subTest(h=h,u=u,dt=dt),self.assertRaises(TectonicsError):
                advect_thickness(h,u,grid,dt)


class ThermalTests(unittest.TestCase):
    def test_known_error_function_value(self):
        self.assertAlmostEqual(float(half_space_temperature(2.,1.,THERMAL)),1142.7007929497148,places=9)

    def test_initial_and_surface_conditions(self):
        close(half_space_temperature([0,1,10],0,THERMAL),[300,1300,1300])
        close(half_space_temperature(0,[0,1,1e6],THERMAL),[300,300,300])

    def test_depth_monotonicity_and_cooling(self):
        self.assertTrue(np.all(np.diff(half_space_temperature([0,1,2,10],1,THERMAL))>=0))
        self.assertTrue(np.all(np.diff(half_space_temperature(2,[0,1,4,100],THERMAL))<=0))

    def test_similarity_scaling(self):
        a=half_space_temperature([0,1,2,4],[1,1,1,1],THERMAL)
        b=half_space_temperature([0,2,4,8],[4,4,4,4],THERMAL)
        close(a,b)

    def test_changed_parameters_change_result(self):
        a=half_space_temperature(2,1,THERMAL)
        b=half_space_temperature(2,1,replace(THERMAL,diffusivity_m2_s=4))
        self.assertLess(float(b),float(a))

    def test_broadcast_and_no_mutation(self):
        depths=np.array([[0.],[1.],[2.]])
        output=half_space_temperature(depths,[0.,1.,4.],THERMAL)
        self.assertEqual(output.shape,(3,3))
        assert_array_equal(depths,[[0],[1],[2]])
        with self.assertRaises(ValueError):
            output.setflags(write=True)

    def test_equal_temperature_limit(self):
        close(half_space_temperature([0,1,2],4,replace(THERMAL,mantle_temperature_k=300)),[300]*3)

    def test_negative_depth_age_and_incompatible_shape(self):
        for depth,age in ((-1,1),(1,-1),([1,2],[1,2,3]),(True,1)):
            with self.subTest(depth=depth,age=age),self.assertRaises(TectonicsError):
                half_space_temperature(depth,age,THERMAL)


class FlexureTests(unittest.TestCase):
    def test_uniform_and_zero_load(self):
        operator=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        close(operator.solve(np.full(16,3.)),np.full(16,3.))
        assert_array_equal(operator.solve(np.zeros(16)),np.zeros(16))

    def test_dense_independent_operator_equivalence(self):
        for n in (7,8,16):
            with self.subTest(n=n):
                grid=PeriodicGrid1D(n,float(n))
                load=np.cos(np.arange(n)*1.7)+np.arange(n)*.03
                expected=np.linalg.solve(dense_operator(grid,ELASTIC),load)
                actual=PeriodicFlexure(grid,ELASTIC).solve(load)
                close(actual,expected)
                close(dense_operator(grid,ELASTIC)@actual,load)

    def test_continuous_sinusoid_second_order(self):
        errors=[]
        for n in (16,32,64):
            grid=PeriodicGrid1D(n,2*np.pi)
            x=np.arange(n)*grid.spacing_m
            expected=np.cos(x)/2 # D=restoration=k=1
            actual=PeriodicFlexure(grid,ELASTIC).solve(np.cos(x))
            errors.append(np.max(np.abs(actual-expected)))
        orders=np.log2(np.array(errors[:-1])/errors[1:])
        self.assertTrue(np.all(orders>CASE['acceptance']['smooth_flexure_order_min']),orders)
        self.assertTrue(np.all(orders<CASE['acceptance']['smooth_flexure_order_max']),orders)

    def test_superposition(self):
        op=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        a=np.arange(16.)/10; b=np.cos(a)
        close(op.solve(2*a-3*b),2*op.solve(a)-3*op.solve(b))

    def test_translation_invariance(self):
        op=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        a=np.zeros(16); a[4]=10
        close(op.solve(np.roll(a,3)),np.roll(op.solve(a),3))

    def test_batch_matches_separate(self):
        op=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        a=np.arange(48.).reshape(3,16)
        close(op.solve(a),np.array([op.solve(row) for row in a]))

    def test_load_change_reuses_setup_not_result(self):
        op=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        with mock.patch('numpy.sin',side_effect=AssertionError('rebuilt operator')):
            close(op.solve(np.ones(16)),np.ones(16))
            close(op.solve(np.full(16,2.)),np.full(16,2.))
        self.assertEqual(op.setup_bytes,9*8)

    def test_parameter_and_grid_change_operator_identity(self):
        a=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        b=PeriodicFlexure(a.grid,replace(ELASTIC,gravity_m_s2=2))
        c=PeriodicFlexure(PeriodicGrid1D(16,32),ELASTIC)
        self.assertNotEqual(a.operator_id,b.operator_id)
        self.assertNotEqual(a.operator_id,c.operator_id)
        close(b.solve(np.ones(16)),np.full(16,.5))

    def test_immutable_coefficients_and_results(self):
        op=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        for a in (op._gain,op.solve(np.ones(16))):
            with self.assertRaises(ValueError):
                a.setflags(write=True)

    def test_invalid_load_and_range_refusal(self):
        op=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        for load in (np.ones(15),np.ones(16,dtype=complex),[np.nan]*16,True):
            with self.subTest(load=str(load)[:40]),self.assertRaises(TectonicsError):
                op.solve(load)
        with self.assertRaises(TectonicsError):
            PeriodicFlexure(PeriodicGrid1D(8,1e-200),ELASTIC)


if __name__=='__main__':
    unittest.main()
