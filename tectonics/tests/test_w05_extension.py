"""Bounded W05 production controls against the independent quadrature oracle."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import math
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.extension import (
    ListricGeometry, PreparedListricExtension, hangingwall_cell_means,
)
from atlas_tectonics.materials import MaterialBoundary, MaterialCohort, MaterialState
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.remapping import advect_ale
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext, CachePolicy, ReuseController
from atlas_tectonics.storage import ArrayStore, StoreLimits
from w05_reference import (
    boundary_exchanges, footwall_means, hanging_wall_means, homogeneous_dilation,
)


EDGES = np.array([-2., -.2, .4, .9, 1.7, 3.5, 7.5])
COHORTS = (MaterialCohort('older', 'rock', 'synthetic-origin-a', -10.),
           MaterialCohort('younger', 'rock', 'synthetic-origin-b', -5.))
FRACTIONS = np.array([.25, .75])


class W05ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def fixture(self, **changes):
        grid = changes.pop('grid', ColumnGrid1D(EDGES, frame_id='synthetic-section'))
        geometry = changes.pop('geometry', ListricGeometry(10., 3., math.atan(1.5),
                                                          .25, 'synthetic-fault'))
        arguments = dict(velocity_m_s=.2, density_kg_m3=2800., width_m=2.,
            cohorts=COHORTS, fractions=FRACTIONS, time_s=0., epoch_id='synthetic-epoch',
            datum_id='synthetic-datum', source_id='synthetic-extension',
            backend='reference', context=self.context)
        arguments.update(changes)
        return PreparedListricExtension(grid, geometry, **arguments)

    @staticmethod
    def reference_geometry(plan):
        return dict(depth_m=plan.geometry.detachment_depth_m,
                    decay_length_m=2., trace_m=plan.geometry.trace_m)

    def test_characteristic_means_and_signed_multicohort_accounts(self):
        with self.fixture() as plan:
            self.assertAlmostEqual(plan.geometry.decay_length_m, 2., delta=4e-16)
            initial = plan.initial
            current = plan.advance(initial, time_s=3.5)
            geometry = self.reference_geometry(plan)
            expected = hanging_wall_means(EDGES, .7, **geometry)
            assert_allclose(current.material.thickness_m, FRACTIONS[:, None]*expected,
                            rtol=3e-13, atol=2e-15)
            exchange = np.asarray(boundary_exchanges(EDGES[0], EDGES[-1], .7, **geometry))
            assert_allclose(current.exchange_m2, FRACTIONS[:, None]*exchange,
                            rtol=3e-13, atol=2e-15)
            assert_array_equal(current.exchange_m2[:, 0], 0.)
            self.assertTrue(np.all(current.exchange_m2[:, 1] < 0.))
            for old, new, account in zip(initial.material.thickness_m,
                                         current.material.thickness_m, current.exchange_m2):
                difference = math.fsum(float((b-a)*dx) for a, b, dx in zip(old, new, np.diff(EDGES)))
                self.assertAlmostEqual(difference, math.fsum(account), delta=3e-14)
            self.assertEqual(current.material.time_s, 3.5)
            self.assertEqual(current.material.cohorts, COHORTS)
            self.assertEqual(current.material.ages_s(), (13.5, 8.5))
            self.assertEqual(current.material.parent_state_id, initial.material.state_id)
            receipt = current.material.transition_record
            self.assertEqual(receipt['operation'], 'listric-characteristic-v1')
            self.assertEqual(receipt['initial_material'], initial.material.state_id)
            self.assertEqual(receipt['account_reference'], 'initial_material')

    def test_continuation_references_initial_family_and_complete_export(self):
        with self.fixture() as plan:
            middle = plan.advance(plan.initial, time_s=3.5)
            continued = plan.advance(middle, time_s=7.)
            direct = plan.advance(plan.initial, time_s=7.)
            assert_array_equal(continued.material.thickness_m, direct.material.thickness_m)
            assert_array_equal(continued.exchange_m2, direct.exchange_m2)
            self.assertEqual(continued.intervals, 2)
            self.assertEqual(direct.intervals, 1)
            self.assertNotEqual(continued.state_id, direct.state_id)  # Different actual histories.
            self.assertIs(plan.advance(continued, time_s=7.), continued)
            empty = plan.advance(continued, time_s=50.)
            assert_array_equal(empty.material.thickness_m, 0.)
            expected = boundary_exchanges(EDGES[0], EDGES[-1], 10., **self.reference_geometry(plan))
            assert_allclose(empty.exchange_m2, FRACTIONS[:, None]*np.asarray(expected),
                            rtol=3e-13, atol=2e-15)
            before = plan.initial.material.thickness_m@np.diff(EDGES)
            assert_allclose(-empty.exchange_m2[:, 1], before, rtol=3e-14, atol=2e-15)

    def test_stationary_footwall_zero_motion_and_immutable_views(self):
        with self.fixture(velocity_m_s=0.) as plan:
            initial_bytes = plan.initial.material.thickness_m.tobytes()
            current = plan.advance(plan.initial, time_s=5.)
            fields = plan.geometry_fields(current)
            assert_array_equal(current.material.thickness_m, plan.initial.material.thickness_m)
            assert_array_equal(current.exchange_m2, 0.)
            assert_array_equal(fields[:, 3], 0.)
            expected = footwall_means(EDGES, crust_thickness_m=10., **self.reference_geometry(plan))
            assert_allclose(fields[:, 1], expected, rtol=2e-15, atol=2e-15)
            assert_allclose(fields[:, 2], 10., rtol=0, atol=2e-15)
            for array in (plan.footwall_thickness_m, fields, current.exchange_m2,
                          current.material.thickness_m):
                with self.assertRaises(ValueError):
                    array.setflags(write=True)
            view = plan.footwall_thickness_m
            view.shape = (2, 3)
            self.assertEqual(plan.footwall_thickness_m.shape, (6,))
            with self.assertRaises(FrozenInstanceError):
                current.intervals = 99
            with self.assertRaises(FrozenInstanceError):
                plan.width_m = 9.
            self.assertEqual(plan.initial.material.thickness_m.tobytes(), initial_bytes)

    def test_tiny_front_cell_integrals_against_quadrature(self):
        geometry = ListricGeometry(10., 3., math.atan(1.5), 0., 'tiny-front')
        for edges, displacement in (([-1e-10, 1e-10, 2e-10], 0.),
                                     ([.125-1e-10, .125+1e-10, .126], .125)):
            grid = ColumnGrid1D(edges, frame_id='tiny-section')
            actual = hangingwall_cell_means(grid, geometry, displacement)
            expected = hanging_wall_means(edges, displacement, depth_m=3., decay_length_m=2., trace_m=0.)
            self.assertTrue(np.all(actual > 0.))
            assert_allclose(actual, expected, rtol=4e-14, atol=0.)

    def test_invalid_definition_clock_and_underflow_guards(self):
        for depth, dip in ((10., .5), (3., 0.), (3., math.pi/2)):
            with self.assertRaises(TectonicsError):
                ListricGeometry(10., depth, dip, 0., 'invalid-control')
        for changes in (dict(fractions=[.2, .7]), dict(fractions=[1.]),
                        dict(transport='implicit'), dict(velocity_m_s=-1.),
                        dict(fractions=[np.nextafter(0., 1.), 1.])):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                self.fixture(**changes)
        with self.fixture(time_s=-1.) as plan:
            with self.assertRaisesRegex(TectonicsError, 'endpoint'):
                plan.advance(plan.initial, time_s=1e-20)
        with self.fixture(velocity_m_s=np.nextafter(0., 1.)) as plan:
            with self.assertRaisesRegex(TectonicsError, 'underflow'):
                plan.advance(plan.initial, time_s=.1)
        with self.fixture() as plan:
            for options in (dict(time_s=-1.), dict(time_s=1., steps=0),
                            dict(time_s=1., steps=2), dict(time_s=1., steps=257),
                            dict(time_s=1., store=object())):
                with self.subTest(options=options), self.assertRaises(TectonicsError):
                    plan.advance(plan.initial, **options)

    def test_foreign_closed_cancel_and_budget_guards_release(self):
        owner = WorkBudget(2_000_000)
        event = Event(); event.set()
        with self.assertRaises(CancelledError):
            self.fixture(budget=owner, cancel=event)
        self.assertEqual(owner.reserved_bytes, 0)
        with self.assertRaises(MemoryLimitError):
            self.fixture(budget=WorkBudget(1))
        plan = self.fixture(budget=owner)
        retained = owner.reserved_bytes
        try:
            with self.fixture(source_id='distinct-mechanism') as other:
                with self.assertRaises(TectonicsError):
                    plan.advance(other.initial, time_s=1.)
            with self.assertRaises(CancelledError):
                plan.advance(plan.initial, time_s=1., cancel=event)
            with self.assertRaises(MemoryLimitError):
                plan.advance(plan.initial, time_s=1., budget=WorkBudget(1, parent=owner))
            for operation in (lambda b: plan.advance(plan.initial, time_s=1., budget=b),
                              lambda b: plan.geometry_fields(plan.initial, budget=b)):
                with self.assertRaises(TectonicsError):
                    operation(WorkBudget(2_000_000))
            self.assertEqual(owner.reserved_bytes, retained)
            child = WorkBudget(1_000_000, parent=owner)
            plan.advance(plan.initial, time_s=1., budget=child)
            self.assertEqual(child.reserved_bytes, 0)
            self.assertEqual(owner.reserved_bytes, retained)
        finally:
            plan.close()
        self.assertEqual(owner.reserved_bytes, 0)
        with self.assertRaises(TectonicsError):
            plan.advance(plan.initial, time_s=1.)
        with self.assertRaises(TectonicsError):
            plan.geometry_fields(plan.initial)

    def test_explicit_muscl_comparison_conserves_without_changing_method(self):
        with self.fixture(transport='muscl') as plan:
            current = plan.advance(plan.initial, time_s=.5, steps=4)
            self.assertEqual(current.intervals, 4)
            self.assertLessEqual(current.max_courant, .5)
            self.assertEqual(current.material.transition_record['operation'], 'ale-cohort-ssprk2-v2')
            assert_array_equal(current.exchange_m2[:, 0], 0.)
            change = (current.material.thickness_m-plan.initial.material.thickness_m)@np.diff(EDGES)
            assert_allclose(change, current.exchange_m2[:, 1], rtol=0, atol=3e-14)
            self.assertTrue(np.all(current.material.thickness_m >= 0.))
            with self.assertRaisesRegex(TectonicsError, 'CFL'):
                plan.advance(plan.initial, time_s=100., steps=1)

    def test_existing_muscl_cache_parity_and_prepared_live_identity(self):
        import atlas_tectonics.extension as extension
        owner = WorkBudget(32_000_000)  # Includes the store's admitted SQLite pages.
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'motion.db',
                            StoreLimits(1024, 1<<20, 4<<20, 4096), budget=owner) as store:
                control = ReuseController()
                with self.fixture(transport='muscl', budget=owner) as plan:
                    options = dict(time_s=.1, store=store, controller=control,
                                   cache_policy=CachePolicy(mode='always'))
                    first = plan.advance(plan.initial, **options)
                    second = plan.advance(plan.initial, **options)
                    self.assertEqual(first.state_id, second.state_id)
                    assert_array_equal(first.material.thickness_m, second.material.thickness_m)
                    assert_array_equal(first.exchange_m2, second.exchange_m2)
                    self.assertEqual(control.statistics()['writes'], 1)
                    self.assertEqual(control.statistics()['hits'], 1)
                    with mock.patch.object(extension, 'hangingwall_cell_means', lambda *a, **kw: None):
                        with self.assertRaises(TectonicsError):
                            plan.advance(plan.initial, **options)

    def test_separate_existing_ale_uniform_dilation(self):
        edges = np.array([-2., -.5, 0., 1., 3.])
        h = np.full(4, 2.); beta = 1.25; duration = .5
        grid = ColumnGrid1D(edges, frame_id='material-following-control')
        state = MaterialState(grid, (COHORTS[0],), h[None, :], time_s=0., epoch_id='synthetic-epoch')
        velocity = (beta-1.)*edges/duration
        closed = MaterialBoundary('closed')
        result = advect_ale(state, velocity, velocity, duration,
                            left=closed, right=closed, backend='numba')
        expected_edges, expected_h = homogeneous_dilation(edges, h, beta)
        assert_array_equal(result.state.grid.edges_m, expected_edges)
        assert_allclose(result.state.thickness_m[0], expected_h, rtol=2e-15, atol=0.)
        assert_allclose(result.state.thickness_m[0]*result.state.grid.widths_m,
                        h*np.diff(edges), rtol=2e-15, atol=0.)
        assert_array_equal(result.face_flux_m2_s, 0.)
        assert_array_equal(result.accounts[:, 6:8], 0.)


if __name__ == '__main__':
    unittest.main()
