"""Focused dry-extension support checks; no frozen-case sweep or timing claim."""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
from threading import Event
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.extension import ListricGeometry, PreparedListricExtension
import atlas_tectonics.extension_support as support_module
from atlas_tectonics.extension_support import (
    ContinuousCellMeanFlexure, ExtensionSupportPolicy, PreparedExtensionSupport,
)
from atlas_tectonics.finite_flexure import FiniteRegionFlexure, FlexureBoundary1D
from atlas_tectonics.materials import MaterialCohort
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.parameters import FlexureParameters
from atlas_tectonics.regional import RegionalGrid1D
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext
from w05_support_reference import (
    piecewise_constant_cell_mean, smooth_listric_response, smooth_listric_cell_mean,
)


ELASTIC = FlexureParameters('synthetic-elastic', 'independent support control',
                             12., 1., 0., 4., 1.)
CONTINUOUS = FlexureBoundary1D('continuous', 'continuous', 'synthetic-infinite-plate')
POLICY = ExtensionSupportPolicy(ELASTIC, 2., .5, .2, 1e-5, 'synthetic-support')
COHORT = MaterialCohort('moving-rock', 'rock', 'synthetic-origin', -5.)


class W05SupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def motion(self, *, cells=80, edges=None, crust=10., **changes):
        grid = ColumnGrid1D(np.linspace(-16., 24., cells+1) if edges is None else edges,
                            frame_id='synthetic-support-section')
        geometry = ListricGeometry(crust, 3., math.atan(1.5), 0., 'synthetic-fault')
        arguments = dict(velocity_m_s=.2, density_kg_m3=2., width_m=2.,
            cohorts=(COHORT,), fractions=[1.], time_s=0., epoch_id='synthetic-epoch',
            datum_id='initial-flat-surface', source_id='synthetic-extension',
            backend='reference', context=self.context)
        arguments.update(changes)
        return PreparedListricExtension(grid, geometry, **arguments)

    def test_exact_cell_means_against_independent_quad_including_tiny_spacing(self):
        for spacing, pressure, tolerance in ((.4, [2., -1., .5, 3.], 2e-11),
                                              (1e-8, [2., -1., .5], 1e-20)):
            with self.subTest(spacing=spacing):
                n = len(pressure)
                edges = np.arange(n+1)*spacing
                point = FiniteRegionFlexure(RegionalGrid1D(n, n*spacing), ELASTIC, CONTINUOUS)
                operator = ContinuousCellMeanFlexure(point)
                actual = operator.solve(pressure)
                expected = []
                for left, right in zip(edges[:-1], edges[1:]):
                    value, uncertainty = piecewise_constant_cell_mean(left, right, edges, pressure,
                        rigidity_n_m=1., restoring_pa_per_m=4., absolute_tolerance_m=tolerance,
                        relative_tolerance=1e-11)
                    expected.append(value)
                    self.assertLessEqual(uncertainty, tolerance)
                assert_allclose(actual, expected, rtol=3e-12, atol=tolerance)
                assert_array_equal(operator.solve(np.zeros(n)), 0.)
                with self.assertRaises(ValueError):
                    actual.setflags(write=True)
                with self.assertRaises(TectonicsError):
                    operator.solve(np.ones(n+1))

    def test_physical_load_total_reference_geometry_and_unchanged_material(self):
        with self.motion() as motion:
            state = motion.advance(motion.initial, time_s=1.)
            before = (state.state_id, state.material.thickness_m.tobytes(), state.exchange_m2.tobytes())
            with PreparedExtensionSupport(motion, POLICY) as support:
                result = support.solve(state)
                values = result.cell_means
                delta = motion.geometry_fields(state)[:, 3]
                assert_allclose(values[:, 0], 2.*delta, rtol=2e-13, atol=2e-14)
                assert_array_equal(values[:, 2], delta)
                assert_array_equal(values[:, 3], delta-values[:, 1])
                assert_array_equal(values[:, 4], -10.-values[:, 1])
                assert_array_equal(values[:, 5], motion.footwall_thickness_m-10.-values[:, 1])
                assert_array_equal(values[:, 6], 10.+delta)
                assert_array_equal(values[:, 7], state.material.thickness_m[0])
                assert_array_equal(values[:, 8], motion.footwall_thickness_m)
                assert_array_equal(values[:, 9], -support.support.area_m2*values[:, 1])
                self.assertEqual(result.face_centre_response.shape, (161, 4))
                self.assertGreater(np.max(np.abs(values[:, 1]-result.face_centre_response[1::2, 0])), 1e-5)
                for array in (result.cell_means, result.face_centre_response):
                    with self.assertRaises(ValueError):
                        array.setflags(write=True)
                descriptor = result.descriptor()
                descriptor['time_s'] = 99.
                self.assertEqual(result.descriptor()['time_s'], 1.)
            self.assertEqual(before, (state.state_id, state.material.thickness_m.tobytes(), state.exchange_m2.tobytes()))

    def test_zero_repeat_and_intervening_outputs_do_not_accumulate(self):
        with self.motion() as motion, PreparedExtensionSupport(motion, POLICY) as support:
            zero = support.solve(motion.initial)
            assert_array_equal(zero.cell_means[:, :4], 0.)
            assert_array_equal(zero.face_centre_response, 0.)
            assert_array_equal(zero.cell_means[:, 9], 0.)
            one = motion.advance(motion.initial, time_s=1.)
            first = support.solve(one)
            support.solve(motion.advance(one, time_s=2.))
            repeated = support.solve(one)
            self.assertEqual(first.result_id, repeated.result_id)
            assert_array_equal(first.cell_means, repeated.cell_means)
            assert_array_equal(first.face_centre_response, repeated.face_centre_response)

    def test_sparse_smooth_reference_has_separate_load_discretisation_error(self):
        with self.motion(cells=160) as motion, PreparedExtensionSupport(motion, POLICY) as support:
            state = motion.advance(motion.initial, time_s=1.)
            result = support.solve(state)
            edges = motion.grid.edges_m
            reference = dict(depth_m=3., decay_length_m=2., trace_m=0., density_kg_m3=2.,
                             gravity_m_s2=1., rigidity_n_m=1., restoring_pa_per_m=4.)
            for cell in (60, 64, 72):
                centre = (edges[cell]+edges[cell+1])/2.
                point, uncertainty = smooth_listric_response(centre, .2, **reference,
                    absolute_tolerances=(1e-9, 1e-10, 1e-11))
                mean, mean_error = smooth_listric_cell_mean(edges[cell], edges[cell+1], .2,
                                                            **reference, absolute_tolerance_m=1e-9)
                # Frozen synthetic comparison tolerances; this is not the exact-
                # same-cell-load test above. Smooth q has not been discretised.
                assert_allclose(result.face_centre_response[2*cell+1, :3], point,
                                rtol=0, atol=2e-3)
                self.assertLessEqual(abs(result.cell_means[cell, 1]-mean), 2e-3+mean_error)
                self.assertTrue(np.all(uncertainty < .01))

    def test_hydrostatic_limit_has_one_rebound_and_correct_net_sign(self):
        elastic = replace(ELASTIC, young_modulus_pa=12e-8)
        point = FiniteRegionFlexure(RegionalGrid1D(5, 50., -25.), elastic, CONTINUOUS)
        mean = ContinuousCellMeanFlexure(point)
        delta = -.2; rho_c = 2.; rho_m = 4.; gravity = 1.
        response = mean.solve(np.full(5, rho_c*gravity*delta))
        self.assertAlmostEqual(response[2], rho_c/rho_m*delta, delta=2e-14)
        self.assertLess(response[2], 0.)
        surface = delta-response[2]
        self.assertAlmostEqual(surface, (1.-rho_c/rho_m)*delta, delta=2e-14)
        self.assertLess(surface, 0.)

    def test_foreign_mantle_muscl_nonuniform_and_front_refusals(self):
        with self.motion() as motion:
            wrong = replace(POLICY, elastic=replace(ELASTIC, density_contrast_kg_m3=1.))
            with self.assertRaisesRegex(TectonicsError, 'mantle'):
                PreparedExtensionSupport(motion, wrong)
            with PreparedExtensionSupport(motion, POLICY) as support:
                with self.motion(source_id='another-source') as other:
                    with self.assertRaises(TectonicsError):
                        support.solve(other.initial)
                beyond = motion.advance(motion.initial, time_s=125.)
                with self.assertRaisesRegex(TectonicsError, 'front'):
                    support.solve(beyond)
        with self.motion(transport='muscl') as motion:
            with self.assertRaisesRegex(TectonicsError, 'characteristic'):
                PreparedExtensionSupport(motion, POLICY)
        with self.motion(edges=[-16., -8., 0., 7., 24.]) as motion:
            with self.assertRaisesRegex(TectonicsError, 'uniform'):
                PreparedExtensionSupport(motion, POLICY)

    def test_cancel_budget_closed_and_live_identity_guards(self):
        owner = WorkBudget(4_000_000)
        event = Event(); event.set()
        with self.motion(budget=owner) as motion:
            retained = owner.reserved_bytes
            with self.assertRaises(CancelledError):
                PreparedExtensionSupport(motion, POLICY, cancel=event)
            with self.assertRaises(MemoryLimitError):
                PreparedExtensionSupport(motion, POLICY, budget=WorkBudget(1, parent=owner))
            with self.assertRaises(TectonicsError):
                PreparedExtensionSupport(motion, POLICY, budget=WorkBudget(4_000_000))
            self.assertEqual(owner.reserved_bytes, retained)
            child = WorkBudget(2_000_000, parent=owner)
            support = PreparedExtensionSupport(motion, POLICY, budget=child)
            try:
                state = motion.advance(motion.initial, time_s=1.)
                child_retained = child.reserved_bytes
                with self.assertRaises(CancelledError):
                    support.solve(state, cancel=event)
                with mock.patch.object(support_module, '_upper_exp', lambda exponent: 1.):
                    with self.assertRaisesRegex(TectonicsError, 'implementation'):
                        support.solve(state)
                support.solve(state)
                self.assertEqual(child.reserved_bytes, child_retained)
            finally:
                support.close()
            self.assertEqual(child.reserved_bytes, 0)
            self.assertEqual(owner.reserved_bytes, retained)
            with self.assertRaises(TectonicsError):
                support.solve(motion.initial)
            motion.advance(motion.initial, time_s=1.)  # Support does not own motion.
            support = PreparedExtensionSupport(motion, POLICY)
            motion.close()
            try:
                with self.assertRaisesRegex(TectonicsError, 'closed'):
                    support.solve(motion.initial)
            finally:
                support.close()
        self.assertEqual(owner.reserved_bytes, 0)

    def test_exterior_tail_and_each_physical_envelope_refuse(self):
        with self.motion(edges=np.linspace(-4., 4., 17)) as motion:
            state = motion.advance(motion.initial, time_s=1.)
            with PreparedExtensionSupport(motion, POLICY) as support:
                with self.assertRaisesRegex(TectonicsError, 'exterior'):
                    support.solve(state)
        with self.motion() as motion:
            state = motion.advance(motion.initial, time_s=1.)
            for field in ('max_abs_displacement_m', 'max_abs_slope', 'max_bending_strain'):
                with self.subTest(field=field):
                    policy = replace(POLICY, **{field: 1e-8})
                    with PreparedExtensionSupport(motion, policy) as support:
                        with self.assertRaisesRegex(TectonicsError, 'envelope'):
                            support.solve(state)
            with PreparedExtensionSupport(motion, POLICY) as support:
                result = support.solve(state)
                descriptor = result.descriptor()
                qright = 2.*3.*math.exp(-(24.-.2)/2.)*(-math.expm1(-.2/2.))
                self.assertGreater(descriptor['exterior_right_bound_pa'], 0.)
                assert_allclose(descriptor['exterior_right_bound_pa'], qright, rtol=2e-13, atol=0.)
                wbound = qright/(math.sqrt(2.)*4.)
                assert_allclose(descriptor['omitted_response_bounds'],
                                [wbound, math.sqrt(2.)*wbound, 2.*wbound], rtol=2e-13, atol=0.)

    def test_small_moving_load_survives_a_large_fixed_crust_baseline(self):
        with self.motion(crust=1e12) as motion, PreparedExtensionSupport(motion, POLICY) as support:
            state = motion.advance(motion.initial, time_s=1e-6)
            kinematic = motion.geometry_fields(state)[:, 3]
            self.assertTrue(np.any(kinematic != 0.))
            self.assertTrue(np.all(1e12+kinematic == 1e12))  # A whole-crust load would erase this.
            result = support.solve(state)
            assert_array_equal(result.cell_means[:, 0], 2.*kinematic)  # A=1 m2 here.
            self.assertTrue(np.any(result.cell_means[:, 0] != 0.))
            assert_array_equal(result.cell_means[:, 3], kinematic-result.cell_means[:, 1])


if __name__ == '__main__':
    unittest.main()
