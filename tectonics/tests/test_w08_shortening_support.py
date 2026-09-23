"""Focused W08 fixed-reference shortening loads and single-owner support."""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
from threading import Event
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.materials import MaterialCohort, MaterialState
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.parameters import FlexureParameters
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.shortening import PreparedShortening, ShorteningInterval
import atlas_tectonics.shortening_support as support_module
from atlas_tectonics.shortening_support import (
    PreparedShorteningSupport, ShorteningSupportPolicy,
)
from w05_support_reference import piecewise_constant_cell_mean, piecewise_constant_response


ELASTIC = FlexureParameters('synthetic-elastic', 'analytic-support-control',
                             12., 1., 0., 4., 1.)
POLICY = ShorteningSupportPolicy(ELASTIC, 4., 2., .8, .8, 'synthetic-support')
COHORTS = (MaterialCohort('a', 'rock-a', 'source-a', -2.),
           MaterialCohort('b', 'rock-b', 'source-b', -1.))


def overlap_volumes(source_edges, thickness, stretch, shift, target_edges, width):
    """Independent scalar geometric integral, not the production projector."""
    result = np.zeros((len(thickness), len(target_edges)-1))
    for c, heights in enumerate(thickness):
        for j, (left, right) in enumerate(zip(target_edges[:-1], target_edges[1:])):
            terms = []
            for i, height in enumerate(heights):
                lo = stretch*source_edges[i]+shift
                hi = stretch*source_edges[i+1]+shift
                terms.append(max(0., min(right, hi)-max(left, lo))*height/stretch*width)
            result[c, j] = math.fsum(terms)
    return result


class W08ShorteningSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def motion(self, *, stretch=.5, velocity=0., heights=None, **changes):
        grid = ColumnGrid1D([0., 1., 2., 3., 4.], frame_id='synthetic-section')
        material = MaterialState(grid, COHORTS,
            np.array([[.2]*4, [.3]*4]) if heights is None else heights,
            time_s=0., epoch_id='synthetic-epoch')
        history = (ShorteningInterval(1., math.log(stretch), velocity, 0., 'synthetic-history'),)
        arguments = dict(density_kg_m3=[2., 3.], width_m=2.,
            datum_id='synthetic-fixed-base', source_id='synthetic-shortening',
            context=self.context)
        arguments.update(changes)
        return PreparedShortening(material, history, **arguments)

    def support(self, motion, policy=POLICY, *, edges=None, height=2., frame='synthetic-section',
                fill=None, **changes):
        grid = ColumnGrid1D(np.linspace(-2., 6., 17) if edges is None else edges, frame_id=frame)
        return PreparedShorteningSupport(motion, grid, policy,
            support_height_m=np.full(grid.cells, height),
            replacement_density_kg_m3=np.zeros(grid.cells) if fill is None else fill,
            geometry_source='synthetic-fixed-load-support', **changes)

    def test_multicohort_overlap_load_integrals_and_single_response(self):
        heights = np.array([[.1, .2, .4, .5], [.4, .1, .3, .2]])
        with self.motion(stretch=.8, velocity=.13, heights=heights) as motion:
            state = motion.evaluate(1.)
            before = (state.state_id, state.material.thickness_m.tobytes(),
                      state.material.grid.edges_m.tobytes())
            with self.support(motion) as support:
                result = support.solve(state)
                edges = support.grid.edges_m
                initial = overlap_volumes([0., 1., 2., 3., 4.], heights, 1., 0., edges, 2.)
                current = overlap_volumes([0., 1., 2., 3., 4.], heights,
                    state.stretch, state.translation_m, edges, 2.)
                dh = (current-initial)/(np.diff(edges)*2.)
                phases = np.array([2., 3.])[:, None]*dh
                assert_allclose(result.phase_load_pa, phases, rtol=1e-13, atol=2e-14)
                q = np.array([math.fsum(column) for column in phases.T])
                values = result.cell_means
                assert_allclose(values[:, 0], q, rtol=1e-13, atol=2e-14)
                assert_allclose(values[:, 2], np.sum(dh, axis=0), rtol=1e-13, atol=2e-14)
                assert_array_equal(values[:, 3], values[:, 2]-values[:, 1])
                assert_array_equal(values[:, 4], -values[:, 1])
                assert_allclose(values[:, 5], np.sum(initial, axis=0)/support.support.area_m2)
                assert_allclose(values[:, 6], np.sum(current, axis=0)/support.support.area_m2)
                for phase in result.phase_load_pa:
                    load_terms = phase*support.support.area_m2
                    self.assertLessEqual(abs(math.fsum(load_terms)),
                        128*np.finfo(float).eps*math.fsum(abs(load_terms)))
                self.assertEqual(result.descriptor()['datum_id'], motion.datum_id)
                self.assertEqual(result.face_centre_response.shape, (33, 4))
            self.assertEqual(before, (state.state_id, state.material.thickness_m.tobytes(),
                                      state.material.grid.edges_m.tobytes()))

    def test_independent_green_integrals_for_analytic_shortening_load(self):
        with self.motion() as motion, self.support(motion) as support:
            result = support.solve(motion.evaluate(1.))
            edges = support.grid.edges_m
            # H0=.5, lambda=.5: +1.3 Pa on [0,2], -1.3 Pa on [2,4].
            expected_q = np.zeros(16)
            expected_q[4:8] = 1.3
            expected_q[8:12] = -1.3
            assert_allclose(result.cell_means[:, 0], expected_q, rtol=0, atol=1e-15)
            for cell in (4, 7, 10):
                mean, error = piecewise_constant_cell_mean(edges[cell], edges[cell+1],
                    edges, expected_q, rigidity_n_m=1., restoring_pa_per_m=4.,
                    absolute_tolerance_m=2e-10)
                self.assertLessEqual(error, 2e-10)
                self.assertAlmostEqual(result.cell_means[cell, 1], mean, delta=2e-10)
                point, uncertainty = piecewise_constant_response((edges[cell]+edges[cell+1])/2,
                    edges, expected_q, rigidity_n_m=1., restoring_pa_per_m=4.,
                    absolute_tolerances=(2e-10, 2e-10, 2e-10))
                self.assertTrue(np.all(uncertainty <= 2e-10))
                assert_allclose(result.face_centre_response[2*cell+1, :3], point,
                                rtol=0, atol=2e-10)

    def test_zero_repeat_and_immutable_results_keep_total_reference(self):
        with self.motion() as motion, self.support(motion) as support:
            zero = support.solve(motion.initial)
            assert_array_equal(zero.cell_means[:, :5], 0.)
            assert_array_equal(zero.phase_load_pa, 0.)
            assert_array_equal(zero.face_centre_response, 0.)
            state = motion.evaluate(1.)
            first = support.solve(state)
            support.solve(motion.evaluate(.5))
            repeated = support.solve(state)
            self.assertEqual(first.result_id, repeated.result_id)
            for a in (first.cell_means, first.phase_load_pa, first.face_centre_response):
                with self.assertRaises(ValueError):
                    a.setflags(write=True)
            with self.assertRaises(AttributeError):
                first.result_id = 'changed'
            descriptor = first.descriptor(); descriptor['time_s'] = 999.
            self.assertEqual(first.descriptor()['time_s'], 1.)
            with self.assertRaises(AttributeError):
                support.policy = POLICY

    def test_dry_hydrostatic_limit_has_one_rebound(self):
        # Small load keeps the sharp-edge strain within its declared linear
        # range while a broad interior approaches the dry hydrostatic limit.
        policy = replace(POLICY, elastic=replace(ELASTIC, young_modulus_pa=12e-8))
        heights = np.array([[.2e-6]*4, [.3e-6]*4])
        with self.motion(heights=heights) as motion, self.support(motion, policy) as support:
            result = support.solve(motion.evaluate(1.))
            self.assertAlmostEqual(result.cell_means[5, 1], 1.3e-6/4., delta=1e-19)
            self.assertAlmostEqual(result.cell_means[5, 3], .5e-6-1.3e-6/4., delta=1e-19)
            self.assertGreater(result.cell_means[5, 3], 0.)
            self.assertLess(result.cell_means[5, 4], 0.)

    def test_reference_current_footprints_and_finite_height_refuse(self):
        with self.motion() as motion:
            with self.assertRaisesRegex(TectonicsError, 'exterior|footprint'):
                self.support(motion, edges=np.linspace(1., 3., 9))
            with self.assertRaisesRegex(TectonicsError, 'finite support'):
                self.support(motion, height=.4)
            with self.support(motion, height=.75) as support:
                with self.assertRaisesRegex(TectonicsError, 'finite support'):
                    support.solve(motion.evaluate(1.))
        with self.motion(stretch=1., velocity=10.) as motion, self.support(motion) as support:
            with self.assertRaisesRegex(TectonicsError, 'exterior|footprint'):
                support.solve(motion.evaluate(1.))

    def test_narrow_tall_parcel_cannot_hide_in_a_wide_column_mean(self):
        heights = np.full((2, 4), .1)
        edges = [-3., 5., 13., 21.]
        with self.motion(stretch=.125, heights=heights) as motion:
            with self.support(motion, edges=edges, height=.5) as support:
                state = motion.evaluate(1.)
                # [0,4] contracts to [0,.5], missing the target centre x=1.
                # Actual H=1.6 m exceeds the .5 m support. Averaged H=.1 m
                # still fits, and this within-cell motion even leaves q=0.
                projection = motion.project(state, support.grid,
                    exterior_ids=('test-left', 'test-right'), source_id='tall-parcel-control')
                averaged = np.sum(projection.volume_m3, axis=0)/support.support.area_m2
                self.assertTrue(np.all(averaged < support.support.height_m))
                assert_allclose(averaged[0], .1, rtol=0, atol=1e-15)
                self.assertGreater(float(np.min(state.material.total_thickness(backend='reference'))), .5)
                with self.assertRaisesRegex(TectonicsError, 'parcel interior.*finite support'):
                    support.solve(state)
        # Apply the same interior coverage requirement when binding reference.
        with self.motion(stretch=1., heights=np.full((2, 4), .4)) as motion:
            with self.assertRaisesRegex(TectonicsError, 'parcel interior.*finite support'):
                self.support(motion, edges=edges, height=.5)

    def test_explicit_uniform_frame_mantle_replacement_and_source_guards(self):
        with self.motion() as motion:
            for args, message in ((dict(edges=[-2., 0., 1., 4., 6.]), 'uniform'),
                                  (dict(frame='foreign-frame'), 'frame'),
                                  (dict(fill=np.ones(16)), 'dry|replacement')):
                with self.subTest(args=args), self.assertRaisesRegex(TectonicsError, message):
                    self.support(motion, **args)
            with self.assertRaisesRegex(TectonicsError, 'mantle'):
                self.support(motion, replace(POLICY, mantle_density_kg_m3=5.))
            with self.support(motion) as support, self.motion(source_id='foreign-source') as other:
                with self.assertRaises(TectonicsError):
                    support.solve(other.initial)
        for field in ('max_abs_displacement_m', 'max_abs_slope', 'max_bending_strain'):
            with self.subTest(field=field), self.assertRaises(TectonicsError):
                replace(POLICY, **{field: 0.})

    def test_each_continuous_physical_envelope_refuses(self):
        with self.motion() as motion:
            state = motion.evaluate(1.)
            for field in ('max_abs_displacement_m', 'max_abs_slope', 'max_bending_strain'):
                with self.subTest(field=field), self.support(motion,
                        replace(POLICY, **{field: 1e-8})) as support:
                    with self.assertRaisesRegex(TectonicsError, 'envelope'):
                        support.solve(state)
            with self.support(motion) as support:
                result = support.solve(state)
                valid = result.descriptor()['continuous_validity_bounds']
                self.assertTrue(np.all(np.array(valid) >=
                    np.max(np.abs(result.face_centre_response[:, :3]), axis=0)))
                self.assertEqual(result.descriptor()['omitted_response_bounds'], [0., 0., 0.])

    def test_cancel_budget_closed_borrowed_motion_and_live_identity(self):
        owner = WorkBudget(4_000_000)
        event = Event(); event.set()
        with self.motion(budget=owner) as motion:
            retained = owner.reserved_bytes
            with self.assertRaises(CancelledError):
                self.support(motion, cancel=event)
            with self.assertRaises(MemoryLimitError):
                self.support(motion, budget=WorkBudget(1, parent=owner))
            with self.assertRaises(TectonicsError):
                self.support(motion, budget=WorkBudget(4_000_000))
            # Projected reference may occupy the motion's one owned view cache.
            child = WorkBudget(2_000_000, parent=owner)
            support = self.support(motion, budget=child)
            try:
                state = motion.evaluate(1.)
                child_retained = child.reserved_bytes
                with self.assertRaises(CancelledError):
                    support.solve(state, cancel=event)
                with mock.patch.object(support_module, '_continuous_envelopes', lambda *args: (0.,)*3):
                    with self.assertRaisesRegex(TectonicsError, 'implementation'):
                        support.solve(state)
                support.solve(state)
                self.assertEqual(child.reserved_bytes, child_retained)
            finally:
                support.close()
            self.assertEqual(child.reserved_bytes, 0)
            self.assertGreaterEqual(owner.reserved_bytes, retained)
            with self.assertRaisesRegex(TectonicsError, 'closed'):
                support.solve(motion.initial)
            motion.evaluate(1.)
            support = self.support(motion)
            motion.close()
            try:
                with self.assertRaisesRegex(TectonicsError, 'closed'):
                    support.solve(motion.initial)
            finally:
                support.close()
        self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
