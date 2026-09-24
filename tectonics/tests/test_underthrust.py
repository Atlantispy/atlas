"""Synthetic oracles for prescribed, conservative vertical-shear underthrusting.

The polygon coordinates and centroid changes below are independent analytic
fixtures. They test a supplied kinematic closure, not predicted collision physics.
"""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
from threading import Event
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geometry import PlanarGeometry
from atlas_tectonics.materials import MaterialCohort
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.underthrust import (
    UnderthrustInterface, UnderthrustParcel, UnderthrustInterval,
    PreparedUnderthrust,
)


FRAME = 'synthetic-x-z-up'


def polygon(vertices, *, frame=FRAME):
    return PlanarGeometry.polygon(vertices, frame_id=frame)


def rectangle(x0, x1, z0, z1, *, frame=FRAME):
    return polygon(((x0, z0), (x1, z0), (x1, z1), (x0, z1)), frame=frame)


def interface(knots=None, **changes):
    if knots is None:
        knots = ((0., 0.), (2., -2.), (4., -2.))
    options = dict(interface_id='synthetic-ramp', frame_id=FRAME,
                   datum_id='synthetic-z-zero', source_id='supplied-interface',
                   detachment_depth_m=2., section_azimuth_deg=90.)
    options.update(changes)
    return UnderthrustInterface(knots, **options)


def parcels():
    return (
        UnderthrustParcel('incoming', 'foot-block', 'footwall',
            MaterialCohort('lower', 'lower-crust', 'finite-donor', -10.),
            rectangle(-1., 1., -5., -4.), 2., -5., 'relative-heat'),
        UnderthrustParcel('overriding', 'hanging-block', 'hangingwall',
            MaterialCohort('upper', 'upper-crust', 'initial-host', None),
            rectangle(-1., 1., 1., 2.), 4., 3., 'relative-heat'),
    )


def interval(end=1., foot=2., hanging=0., qfoot=7., qhanging=-3.):
    return UnderthrustInterval(end, foot, hanging, qfoot, qhanging,
                              'prescribed-horizontal-motion', 'supplied-force')


def fixture(*, fault=None, material=None, histories=None, receivers=None, **changes):
    options = dict(time_s=0., epoch_id='synthetic-seconds', width_m=3.,
                   gravity_m_s2=10., exterior_id='retained-exterior',
                   source_id='synthetic-underthrust-case',
                   host_space_source_id='complete-synthetic-inventory')
    options.update(changes)
    if receivers is None:
        receivers = (('visible', rectangle(-10., 20., -20., 20.)),)
    return PreparedUnderthrust(
        interface() if fault is None else fault,
        parcels() if material is None else material,
        (interval(),) if histories is None else histories,
        receiver_regions=receivers, **options)


class UnderthrustTests(unittest.TestCase):
    def assertSameAreaGeometry(self, actual, expected):
        self.assertEqual(actual.frame_id, expected.frame_id)
        scale = max(actual.area_m2, expected.area_m2, 1.)
        self.assertLessEqual(
            actual.overlay(expected, 'symmetric_difference').area_m2,
            1e-12 * scale)

    def test_exact_ramp_flat_mapping_area_and_analytic_centroid(self):
        # For x in [-1, 1], dz = -2 + abs(x), so mean dz is -1.5.
        expected = polygon(((1., -6.), (2., -7.), (3., -6.),
                            (3., -5.), (2., -6.), (1., -5.)))
        with fixture() as plan:
            result = plan.evaluate(1.)
            self.assertSameAreaGeometry(result.polygons[0], expected)
            self.assertAlmostEqual(result.polygons[0].area_m2, 2.)
            self.assertSameAreaGeometry(result.polygons[1], parcels()[1].polygon)
            np.testing.assert_allclose(result.volume_m3.sum(axis=1), [6., 6.], rtol=1e-14)
            np.testing.assert_allclose(result.mass_kg.sum(axis=1), [12., 24.], rtol=1e-14)
            np.testing.assert_allclose(result.gravitational_change_j, [-180., 0.], atol=1e-12)
            self.assertEqual(result.parcel_ids, ('incoming', 'overriding'))
            self.assertEqual(result.time_s, 1.)
            self.assertEqual(result.plan_id, plan.plan_id)
            self.assertTrue(result.state_id)

    def test_flat_interface_is_rigid_translation_for_both_blocks(self):
        flat = interface(((0., 0.), (4., 0.)), detachment_depth_m=0.)
        with fixture(fault=flat, histories=(interval(hanging=.5),)) as plan:
            result = plan.evaluate(1.)
            self.assertSameAreaGeometry(result.polygons[0], rectangle(1., 3., -5., -4.))
            self.assertSameAreaGeometry(result.polygons[1], rectangle(-.5, 1.5, 1., 2.))
            np.testing.assert_array_equal(result.displacement_m, [2., .5])
            np.testing.assert_allclose(result.gravitational_change_j, [0., 0.], atol=1e-12)

    def test_motion_wholly_on_dipping_segment_is_rigid_translation(self):
        fault = interface(((0., 0.), (10., -5.), (12., -5.)),
                          detachment_depth_m=5.)
        lower, upper = parcels()
        lower = replace(lower, polygon=rectangle(2., 3., -5., -4.))
        upper = replace(upper, polygon=rectangle(2., 3., 1., 2.))
        with fixture(fault=fault, material=(lower, upper),
                     histories=(interval(foot=1.),)) as plan:
            result = plan.evaluate(1.)
            self.assertSameAreaGeometry(result.polygons[0], rectangle(3., 4., -5.5, -4.5))
            self.assertAlmostEqual(result.gravitational_change_j[0], -30.)

    def test_interface_metadata_dip_detachment_and_frame_refusals(self):
        for kwargs in ({'interface_id': ''}, {'source_id': ''}, {'datum_id': ''},
                       {'frame_id': ''}, {'detachment_depth_m': 3.},
                       {'section_azimuth_deg': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TectonicsError):
                interface(**kwargs)
        for knots in (((0., 0.), (1., 1.), (2., 1.)),
                      ((0., 0.), (0., -2.), (2., -2.)),
                      ((0., 0.), (2., -2.))):
            with self.subTest(knots=knots), self.assertRaises(TectonicsError):
                interface(knots)
        lower, upper = parcels()
        wrong = replace(lower, polygon=rectangle(-1., 1., -5., -4., frame='foreign'))
        with self.assertRaises(TectonicsError):
            fixture(material=(wrong, upper))

    def test_role_half_plane_and_required_block_refusals(self):
        lower, upper = parcels()
        for wrong in (replace(lower, polygon=rectangle(-1., 1., -.5, .5)),
                      replace(lower, polygon=upper.polygon)):
            with self.subTest(polygon=wrong.polygon.geometry_id), self.assertRaises(TectonicsError):
                fixture(material=(wrong, upper))
        with self.assertRaises(TectonicsError):
            fixture(material=(lower,))
        second = replace(lower, parcel_id='second-foot', block_id='other-foot-block',
                         polygon=rectangle(-4., -3., -5., -4.))
        with self.assertRaises(TectonicsError):
            fixture(material=(lower, upper, second))

    def test_initial_material_overlap_refuses(self):
        lower, upper = parcels()
        overlapping = replace(lower, parcel_id='duplicate-space',
                              polygon=rectangle(0., 2., -5., -4.))
        with self.assertRaises(TectonicsError):
            fixture(material=(lower, upper, overlapping))

    def test_receivers_must_be_disjoint_named_and_in_the_same_frame(self):
        for receivers in (
            (('a', rectangle(-2., 2., -10., 10.)),
             ('b', rectangle(1., 3., -10., 10.))),
            (('', rectangle(-2., 2., -10., 10.)),),
            (('a', rectangle(-2., 2., -10., 10., frame='foreign')),),
        ):
            with self.subTest(receivers=tuple(x[0] for x in receivers)), self.assertRaises(TectonicsError):
                fixture(receivers=receivers)
        with self.assertRaises(TectonicsError):
            fixture(host_space_source_id='')

    def test_stationary_host_collision_between_clear_endpoints_refuses(self):
        flat = interface(((0., 0.), (4., 0.)), detachment_depth_m=0.)
        lower, upper = parcels()
        lower = replace(lower, polygon=rectangle(0., 1., -2., -1.))
        upper = replace(upper, polygon=rectangle(0., 1., 1., 2.))
        host = UnderthrustParcel('resident', 'stationary-host', 'host',
            MaterialCohort('resident-cohort', 'mantle', 'existing-host', None),
            rectangle(2., 3., -2., -1.), 5., None, None)
        # Incoming x is [0,1] initially and [4,5] finally; only its path hits host.
        with self.assertRaises(TectonicsError):
            with fixture(fault=flat, material=(lower, upper, host),
                         histories=(interval(foot=4.),)) as plan:
                plan.evaluate(1.)
        safe_host = replace(host, polygon=rectangle(10., 11., -2., -1.))
        with fixture(fault=flat, material=(lower, upper, safe_host),
                     histories=(interval(foot=4.),)) as plan:
            result = plan.evaluate(1.)
            self.assertSameAreaGeometry(result.polygons[2], safe_host.polygon)
            self.assertAlmostEqual(result.mass_kg[2].sum(), 15.)
            self.assertAlmostEqual(result.gravitational_change_j[2], 0.)

    def test_crop_retains_exterior_tagged_mass_and_signed_enthalpy(self):
        receivers = (('visible', rectangle(-10., 2., -20., 20.)),)
        with fixture(receivers=receivers) as plan:
            result = plan.evaluate(1.)
            self.assertEqual(result.destination_ids, ('visible', 'retained-exterior'))
            self.assertEqual(result.enthalpy_known, (True, True))
            np.testing.assert_allclose(result.volume_m3, [[3., 3.], [6., 0.]], atol=1e-12)
            np.testing.assert_allclose(result.mass_kg, [[6., 6.], [24., 0.]], atol=1e-12)
            np.testing.assert_allclose(result.enthalpy_j, [[-30., -30.], [72., 0.]], atol=1e-12)
            self.assertAlmostEqual(math.fsum(result.enthalpy_j.ravel()), 12.)
            record = result.descriptor()
            self.assertTrue(record)

    def test_unknown_heat_is_explicitly_masked_and_not_inferred_from_work(self):
        lower, upper = parcels()
        upper = replace(upper, specific_enthalpy_j_kg=None, enthalpy_source_id=None)
        with fixture(material=(lower, upper)) as plan:
            result = plan.evaluate(1.)
            self.assertEqual(result.enthalpy_known, (True, False))
            self.assertAlmostEqual(result.enthalpy_j[0].sum(), -60.)
            self.assertAlmostEqual(result.mass_kg[1].sum(), 24.)

    def test_generalised_boundary_work_is_separate_from_gravity_and_heat(self):
        with fixture(histories=(interval(hanging=.5),)) as plan:
            initial = plan.evaluate(0.)
            result = plan.evaluate(1.)
            np.testing.assert_allclose(result.boundary_work_j, [14., -1.5], atol=1e-12)
            np.testing.assert_allclose(result.gravitational_change_j, [-180., -75.], atol=1e-12)
            np.testing.assert_allclose(result.enthalpy_j.sum(axis=1),
                                       initial.enthalpy_j.sum(axis=1), atol=1e-12)
            self.assertNotAlmostEqual(result.boundary_work_j.sum(),
                                      result.gravitational_change_j.sum())

    def test_event_partition_invariance_and_latest_output_reuse(self):
        results = []
        for count in (1, 2, 4):
            histories = tuple(interval(end=(i + 1.) / count, hanging=.5)
                              for i in range(count))
            with fixture(histories=histories) as plan:
                plan.evaluate(.375)
                result = plan.evaluate(1.)
                counts = plan.statistics()
                self.assertIs(plan.evaluate(1.), result)
                after = plan.statistics()
                self.assertEqual(after['computed_outputs'], counts['computed_outputs'])
                self.assertEqual(after['latest_hits'], counts['latest_hits'] + 1)
                results.append(result)
        for result in results[1:]:
            for actual, expected in zip(result.polygons, results[0].polygons):
                self.assertSameAreaGeometry(actual, expected)
            for field in ('volume_m3', 'mass_kg', 'enthalpy_j', 'boundary_work_j',
                          'gravitational_change_j', 'displacement_m'):
                np.testing.assert_allclose(getattr(result, field), getattr(results[0], field),
                                           rtol=1e-13, atol=1e-12)

    def test_history_input_and_evaluation_time_refusals(self):
        for kwargs in ({'foot': 0., 'hanging': 1.}, {'foot': float('nan')},
                       {'qfoot': float('inf')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TectonicsError):
                bad = interval(**kwargs)
                with fixture(histories=(bad,)):
                    pass
        for ends in ((0.,), (1., 1.)):
            with self.subTest(ends=ends), self.assertRaises(TectonicsError):
                fixture(histories=tuple(interval(end=end) for end in ends))
        with fixture() as plan:
            for time in (-1., 2., float('nan'), True):
                with self.subTest(time=time), self.assertRaises(TectonicsError):
                    plan.evaluate(time)

    def test_source_verification_remains_live_on_output_cache_hit(self):
        with fixture() as plan:
            plan.evaluate(1.)
            with mock.patch.object(ExecutionContext, 'verify',
                                   side_effect=TectonicsError('synthetic source drift')) as verify:
                with self.assertRaisesRegex(TectonicsError, 'synthetic source drift'):
                    plan.evaluate(1.)
                self.assertTrue(verify.called)

    def test_cancellation_budget_release_and_closed_plan(self):
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(CancelledError):
            fixture(cancel=cancelled)
        too_small = WorkBudget(1)
        with self.assertRaises(MemoryLimitError):
            fixture(budget=too_small)
        self.assertEqual(too_small.reserved_bytes, 0)
        budget = WorkBudget(16 * 1024**2)
        plan = fixture(budget=budget)
        try:
            plan.evaluate(1.)
            self.assertGreater(budget.reserved_bytes, 0)
        finally:
            plan.close()
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaises(TectonicsError):
            plan.evaluate(1.)

    def test_inputs_and_output_arrays_descriptors_are_immutable(self):
        knots = np.array(((0., 0.), (2., -2.), (4., -2.)))
        fault = interface(knots)
        material = parcels()
        with fixture(fault=fault, material=material) as plan:
            knots[:] = 999.
            result = plan.evaluate(1.)
            self.assertAlmostEqual(result.gravitational_change_j[0], -180.)
            with self.assertRaises(AttributeError):
                material[0].density_kg_m3 = 99.
            with self.assertRaises(AttributeError):
                result.time_s = 99.
            for field in ('volume_m3', 'mass_kg', 'enthalpy_j', 'boundary_work_j',
                          'gravitational_change_j', 'displacement_m'):
                values = getattr(result, field)
                shape = values.shape
                with self.subTest(field=field), self.assertRaises(ValueError):
                    values.flat[0] = 99.
                with self.subTest(field=field), self.assertRaises(ValueError):
                    values.setflags(write=True)
                values.shape = (values.size,)
                self.assertEqual(getattr(result, field).shape, shape)
            record = result.descriptor()
            record['caller-injected'] = 'must-not-persist'
            self.assertNotIn('caller-injected', result.descriptor())

    def test_narrow_material_is_not_diluted_out_of_receiving_region(self):
        lower, upper = parcels()
        lower = replace(lower, polygon=rectangle(-.001, .001, -5., -4.))
        with fixture(material=(lower, upper),
                     receivers=(('right', rectangle(2., 10., -20., 20.)),)) as plan:
            result = plan.evaluate(1.)
            np.testing.assert_allclose(result.mass_kg[0], [.006, .006], rtol=1e-10)
            np.testing.assert_allclose(result.enthalpy_j[0], [-.03, -.03], rtol=1e-10)

    def test_nonzero_motion_and_work_underflow_are_refused(self):
        tiny = np.nextafter(0., 1.)
        for event in (interval(end=.5, foot=tiny, qfoot=1.),
                      interval(end=1., foot=.5, qfoot=tiny)):
            with self.subTest(event=event), fixture(histories=(event,)) as plan:
                with self.assertRaises(TectonicsError):
                    plan.evaluate(event.end_time_s)

    def test_loaded_underthrust_class_method_is_in_execution_identity(self):
        with ExecutionContext('scipy') as context:
            with mock.patch.object(UnderthrustInterface, 'height', lambda self, x: x):
                with self.assertRaisesRegex(TectonicsError, 'loaded implementation changed'):
                    context.verify()


if __name__ == '__main__':
    unittest.main()
